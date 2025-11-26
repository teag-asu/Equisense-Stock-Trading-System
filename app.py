import os
from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify
from datetime import datetime, timedelta
from threading import Thread
import sqlite3
import bcrypt
import json
import time
import random
import math

app = Flask(__name__)

app.secret_key = 'team34' # needed for flash messages and session management
#app.secret_key = os.environ.get("FLASK_SECRET_KEY", "dev_default_key") this should be used in the deployed version of the app

DB_NAME = 'stock_trading.db'

def init_db_wal():
    conn = sqlite3.connect(DB_NAME)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    conn.close()

init_db_wal()


# connect to the database
def get_db_connection():
    conn = sqlite3.connect(DB_NAME, timeout=5, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA busy_timeout = 5000;")
    return conn


# password hashing helpers
def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()

def verify_password(password: str, hashed: str) -> bool:
    return bcrypt.checkpw(password.encode(), hashed.encode())


# admin helper
def require_admin():
    """
    Returns None if current session user is an admin.
    Otherwise returns a redirect response (to login or dashboard) which the caller should return.
    """
    if 'user_id' not in session:
        flash("You must be logged in.", "error")
        return redirect(url_for('login'))

    conn = get_db_connection()
    user = conn.execute(
        'SELECT is_admin FROM users WHERE user_id = ?',
        (session['user_id'],)
    ).fetchone()
    conn.close()

    if not user:
        flash("User not found.", "error")
        return redirect(url_for('login'))

    # If DB doesn't have is_admin column, treat as non-admin (0)
    is_admin = user['is_admin'] if 'is_admin' in user.keys() else 0
    if int(is_admin) != 1:
        flash("Administrator access required.", "error")
        # If there's a logged-in user, send them to their dashboard
        if 'user_id' in session:
            return redirect(url_for('dashboard', user_id=session.get('user_id')))
        return redirect(url_for('login'))

    return None


# home / login page
@app.route('/')
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']

        conn = get_db_connection()
        user = conn.execute(
            'SELECT * FROM users WHERE username = ?',
            (username,)
        ).fetchone()
        conn.close()

        # ensure user exists and verify password hash
        if user and verify_password(password, user['password_hash']):
            session['user_id'] = user['user_id']  # store session login

            # store admin flag in session if column exists
            is_admin = user['is_admin'] if 'is_admin' in user.keys() else 0
            session['is_admin'] = int(is_admin)
            log_event(
                1,  # User Login
                f"User '{username}' logged in successfully.",
                user_id=user['user_id']
            )
            flash(f"Welcome back, {user['username']}!", "success")
            return redirect(url_for('dashboard', user_id=user['user_id']))
        else:
            if user:
                log_event(
                    2,  # Failed Login
                    f"Failed login attempt for user '{username}'.",
                    user_id=user['user_id']
                )
            flash("Invalid username or password.", "error")
            return redirect(url_for('login'))
    return render_template('login.html')



@app.route('/register', methods=['POST'])
def register():
    username = request.form['username']
    email = request.form['email']
    password = request.form['password']

    password_hash = hash_password(password)

    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute(
            'INSERT INTO users (username, email, password_hash, balance) VALUES (?, ?, ?, ?)',
            (username, email, password_hash, 0.0)
        )
        conn.commit()
        log_event(
            4,  # Account Registered
            f"User account '{username}' created.",
            user_id=cursor.lastrowid
        )

        flash("Account created successfully! Please log in.", "success")

    except sqlite3.IntegrityError:
        flash("Username or email already exists.", "error")

    finally:
        conn.close()

    return redirect(url_for('login'))



# logout function
@app.route('/logout', methods=['POST'])
def logout():
    # get info before clearing the session
    user_id = session.get('user_id')
    username = None
    if user_id is not None:
        # look up the username from the DB
        conn = get_db_connection()
        cur = conn.execute("SELECT username FROM users WHERE user_id = ?", (user_id,))
        row = cur.fetchone()
        conn.close()
        if row:
            username = row['username']
    log_event(
        3,  # user logout
        f"User '{username}' logged out." if username else "Unknown user logged out.",
        user_id=user_id
    )
    session.clear()  # clear entire session including is_admin
    flash("You have been logged out.", "success")
    return redirect(url_for('login'))


# trading dashboard
@app.route('/dashboard/<int:user_id>')
def dashboard(user_id):
    # Require login
    if 'user_id' not in session or session['user_id'] != user_id:
        flash("You must be logged in to view that page.", "error")
        return redirect(url_for('login'))

    # Pagination params
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 20, type=int)
    offset = (page - 1) * per_page

    conn = get_db_connection()
    user = conn.execute(
        'SELECT * FROM users WHERE user_id = ?', (user_id,)
    ).fetchone()

    if not user:
        flash("User not found.", "error")
        conn.close()
        return redirect(url_for('login'))

    # ----- AVAILABLE STOCKS -----
    available_stocks = conn.execute('''
        SELECT s.stock_id, s.symbol, s.company_name, s.price,
               COALESCE(ph_latest.price - ph_prev.price, 0) AS last_change
        FROM stocks s
        LEFT JOIN (
            SELECT ph1.stock_id, ph1.price
            FROM price_history ph1
            JOIN (
                SELECT stock_id, MAX(timestamp) AS max_time
                FROM price_history
                GROUP BY stock_id
            ) latest ON ph1.stock_id = latest.stock_id AND ph1.timestamp = latest.max_time
        ) ph_latest ON s.stock_id = ph_latest.stock_id
        LEFT JOIN (
            SELECT ph2.stock_id, ph2.price
            FROM price_history ph2
            JOIN (
                SELECT stock_id, MAX(timestamp) AS prev_time
                FROM price_history
                WHERE timestamp < (
                    SELECT MAX(timestamp) 
                    FROM price_history ph3 
                    WHERE ph3.stock_id = price_history.stock_id
                )
                GROUP BY stock_id
            ) prev ON ph2.stock_id = prev.stock_id AND ph2.timestamp = prev.prev_time
        ) ph_prev ON s.stock_id = ph_prev.stock_id
        ORDER BY s.symbol
    ''').fetchall()

    # ----- PORTFOLIO -----
    portfolio = conn.execute('''
        SELECT s.stock_id, s.symbol, s.company_name, s.price AS current_price,
               p.quantity, p.avg_cost, p.total_invested,
               (p.quantity * s.price) AS value,
               (s.price - p.avg_cost) * p.quantity AS unrealized_pl,
               COALESCE(ph_latest.price - ph_prev.price, 0) AS last_change
        FROM portfolio p
        JOIN stocks s ON p.stock_id = s.stock_id
        LEFT JOIN (
            SELECT ph1.stock_id, ph1.price
            FROM price_history ph1
            JOIN (
                SELECT stock_id, MAX(timestamp) AS max_time
                FROM price_history
                GROUP BY stock_id
            ) latest ON ph1.stock_id = latest.stock_id AND ph1.timestamp = latest.max_time
        ) ph_latest ON s.stock_id = ph_latest.stock_id
        LEFT JOIN (
            SELECT ph2.stock_id, ph2.price
            FROM price_history ph2
            JOIN (
                SELECT stock_id, MAX(timestamp) AS prev_time
                FROM price_history
                WHERE timestamp < (
                    SELECT MAX(timestamp)
                    FROM price_history ph3
                    WHERE ph3.stock_id = price_history.stock_id
                )
                GROUP BY stock_id
            ) prev ON ph2.stock_id = prev.stock_id AND ph2.timestamp = prev.prev_time
        ) ph_prev ON s.stock_id = ph_prev.stock_id
        WHERE p.user_id = ? AND p.quantity > 0
        ORDER BY s.symbol
    ''', (user_id,)).fetchall()


    # ----- PERFORMANCE METRICS -----
    total_deposited = user["total_deposited"] or 0
    total_withdrawn = user["total_withdrawn"] or 0
    cash_balance = user["balance"]
    portfolio_value = sum(p["value"] for p in portfolio) if portfolio else 0
    overall_profit = (portfolio_value + cash_balance + total_withdrawn) - total_deposited
    profit_pct = (overall_profit / total_deposited * 100) if total_deposited > 0 else 0

    # ----- PRICE HISTORY CHART DATA -----
    held_ids = [p["stock_id"] for p in portfolio]
    if held_ids:
        placeholders = ",".join("?" * len(held_ids))
        price_rows = conn.execute(f'''
            SELECT stock_id, price, timestamp
            FROM price_history
            WHERE stock_id IN ({placeholders})
            ORDER BY timestamp ASC
        ''', held_ids).fetchall()
    else:
        price_rows = []

    portfolio_history = {}
    for row in price_rows:
        ts = row["timestamp"]
        price = row["price"]
        sid = row["stock_id"]
        qty = next((p["quantity"] for p in portfolio if p["stock_id"] == sid), 0)
        if qty == 0:
            continue
        portfolio_history.setdefault(ts, 0)
        portfolio_history[ts] += qty * price

    chart_labels = sorted(portfolio_history.keys())
    chart_values = [portfolio_history[t] for t in chart_labels]

    # ----- TRANSACTION HISTORY -----
    total_transactions = conn.execute(
        'SELECT COUNT(*) FROM transaction_history WHERE user_id = ?', (user_id,)
    ).fetchone()[0] or 0
    total_pages = (total_transactions + per_page - 1) // per_page

    transaction_history = conn.execute('''
        SELECT th.*, s.symbol
        FROM transaction_history th
        JOIN stocks s ON th.stock_id = s.stock_id
        WHERE th.user_id = ?
        ORDER BY th.timestamp DESC
        LIMIT ? OFFSET ?
    ''', (user_id, per_page, offset)).fetchall()

    conn.close()

    return render_template(
        'dashboard.html',
        user=user,
        balance=cash_balance,
        portfolio=portfolio,
        available_stocks=available_stocks,
        transaction_history=transaction_history,
        total_transactions=total_transactions,
        total_pages=total_pages,
        page=page,
        per_page=per_page,
        user_id=user_id,
        overall_profit=overall_profit,
        profit_pct=profit_pct,
        chart_labels=chart_labels,
        chart_values=chart_values
    )



# ----- API: Live stock prices -----
@app.route("/api/prices")
def api_prices():
    conn = get_db_connection()
    stocks = conn.execute('''
        WITH latest_prices AS (
            SELECT ph1.stock_id, ph1.price,
                   ROW_NUMBER() OVER (PARTITION BY ph1.stock_id ORDER BY ph1.id DESC) AS rn
            FROM price_history ph1
        )
        SELECT s.stock_id, s.symbol, s.company_name, s.price,
               (lp1.price - lp2.price) AS last_change
        FROM stocks s
        LEFT JOIN latest_prices lp1 ON s.stock_id = lp1.stock_id AND lp1.rn = 1
        LEFT JOIN latest_prices lp2 ON s.stock_id = lp2.stock_id AND lp2.rn = 2
        ORDER BY s.symbol
    ''').fetchall()
    conn.close()

    return jsonify([
        {
            "stock_id": s["stock_id"],
            "symbol": s["symbol"],
            "company_name": s["company_name"],
            "price": s["price"],
            "last_change": s["last_change"] or 0
        }
        for s in stocks
    ])


    return jsonify([
        {
            "stock_id": s["stock_id"],
            "symbol": s["symbol"],
            "company_name": s["company_name"],
            "price": s["price"],
            "last_change": s["last_change"] or 0
        }
        for s in stocks
    ])


#Price history API, used for stock chart
@app.route('/api/price_history/<int:stock_id>')
def api_price_history(stock_id):
    conn = get_db_connection()
    # Get all price history entries for the stock, oldest first
    rows = conn.execute('''
        SELECT price, timestamp
        FROM price_history
        WHERE stock_id = ?
        ORDER BY timestamp ASC
    ''', (stock_id,)).fetchall()
    conn.close()

    # Convert to JSON-friendly format
    data = {
        "stock_id": stock_id,
        "timestamps": [row["timestamp"] for row in rows],
        "prices": [row["price"] for row in rows]
    }

    return jsonify(data)



@app.route('/depositwithdraw/<int:user_id>', methods=['POST'])
def depositwithdraw(user_id):
    # Security
    if 'user_id' not in session or session['user_id'] != user_id:
        flash("Unauthorized.", "error")
        return redirect(url_for('login'))

    # Inputs
    amount = float(request.form['amount'])
    action = request.form['action']

    if amount <= 0:
        flash("Amount must be greater than zero.", "error")
        return redirect(url_for('dashboard', user_id=user_id))

    conn = get_db_connection()
    conn.row_factory = sqlite3.Row

    user = conn.execute(
        'SELECT balance, total_deposited, total_withdrawn FROM users WHERE user_id = ?',
        (user_id,)
    ).fetchone()

    if not user:
        conn.close()
        flash("User not found.", "error")
        return redirect(url_for('login'))

    balance = user['balance']
    total_deposited = user['total_deposited']
    total_withdrawn = user['total_withdrawn']

    try:
        if action == 'deposit':
            new_balance = balance + amount
            new_total_deposited = total_deposited + amount

            conn.execute('''
                UPDATE users
                SET balance = ?, total_deposited = ?
                WHERE user_id = ?
            ''', (new_balance, new_total_deposited, user_id))

            msg = f"User {user_id} deposited ${amount:.2f}."
            log_type = 10  # deposit event
            flash(f"Deposited ${amount:.2f}.", "success")

        elif action == 'withdraw':
            if balance < amount:
                conn.close()
                flash("Insufficient funds.", "error")
                return redirect(url_for('dashboard', user_id=user_id))

            new_balance = balance - amount
            new_total_withdrawn = total_withdrawn + amount

            conn.execute('''
                UPDATE users
                SET balance = ?, total_withdrawn = ?
                WHERE user_id = ?
            ''', (new_balance, new_total_withdrawn, user_id))

            msg = f"User {user_id} withdrew ${amount:.2f}."
            log_type = 11  # withdrawal event
            flash(f"Withdrew ${amount:.2f}.", "success")

        else:
            conn.close()
            flash("Invalid action.", "error")
            return redirect(url_for('dashboard', user_id=user_id))

        conn.commit()
    finally:
        conn.close()

    log_event(log_type, msg, user_id=user_id)

    return redirect(url_for('dashboard', user_id=user_id))




# buy stock function
@app.route('/buy_stock/<int:user_id>', methods=['POST'])
def buy_stock(user_id):
    if 'user_id' not in session or session['user_id'] != user_id:
        flash("Unauthorized.", "error")
        return redirect(url_for('login'))

    # check market status server-side and block trades if closed
    ms = get_market_status()
    if ms.get("status") != "open":
        next_open = ms.get("next_open")
        next_text = f" Next open: {next_open}." if next_open else ""
        flash(f"Market is closed: {ms.get('reason')}.{next_text}", "error")
        log_event(
            31, #buy failure
            f"Buy failed for user {user_id}: market closed ({ms.get('reason')}).",
            user_id=user_id
        )

        return redirect(url_for('dashboard', user_id=user_id))

    stock_id = int(request.form['stock_id'])
    quantity = int(request.form['quantity'])
    
    if quantity <= 0:
        flash("Quantity must be greater than zero.", "error")
        log_event(
            31, #buy failure
            f"Buy failed for user {user_id}: quantity <= 0.",
            user_id=user_id
        )

        return redirect(url_for('dashboard', user_id=user_id))
    
    conn = get_db_connection()
    
    try:
        user = conn.execute('SELECT * FROM users WHERE user_id = ?', (user_id,)).fetchone()
        stock = conn.execute('SELECT * FROM stocks WHERE stock_id = ?', (stock_id,)).fetchone()
        
        if not user or not stock:
            flash("User or stock not found.", "error")
            log_event(
                31, #buy failure
                f"Buy failed for user {user_id}: user or stock not found.",
                user_id=user_id
            )

            return redirect(url_for('dashboard', user_id=user_id))
        
        total_cost = quantity * stock['price']
        
        if user['balance'] < total_cost:
            flash(f"Insufficient funds. Need ${total_cost:.2f}, have ${user['balance']:.2f}", "error")
            log_event(
                31, #buy failure
                f"Buy failed for user {user_id}: insufficient funds (needed {total_cost}, had {user['balance']}).",
                user_id=user_id
            )

            return redirect(url_for('dashboard', user_id=user_id))
        
        # update user balance
        new_balance = user['balance'] - total_cost
        conn.execute('UPDATE users SET balance = ? WHERE user_id = ?', (new_balance, user_id))
        
        existing_position = conn.execute(
            'SELECT * FROM portfolio WHERE user_id = ? AND stock_id = ?', 
            (user_id, stock_id)
        ).fetchone()
        
        if existing_position:
            new_quantity = existing_position['quantity'] + quantity
            new_total_invested = existing_position['total_invested'] + total_cost
            new_avg_cost = new_total_invested / new_quantity
            
            conn.execute('''
                UPDATE portfolio 
                SET quantity = ?, avg_cost = ?, total_invested = ?, last_updated = CURRENT_TIMESTAMP
                WHERE user_id = ? AND stock_id = ?
            ''', (new_quantity, new_avg_cost, new_total_invested, user_id, stock_id))
        else:
            conn.execute('''
                INSERT INTO portfolio (user_id, stock_id, quantity, avg_cost, total_invested, last_updated)
                VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ''', (user_id, stock_id, quantity, stock['price'], total_cost))
        
        conn.execute('''
            INSERT INTO orders (user_id, stock_id, order_type, quantity, price, cash_after)
            VALUES (?, ?, 'BUY', ?, ?, ?)
        ''', (user_id, stock_id, quantity, stock['price'], new_balance))
        
        conn.execute('''
            INSERT INTO transaction_history 
            (user_id, stock_id, order_type, quantity, price, total_value, cash_before, cash_after, realized_pl)
            VALUES (?, ?, 'BUY', ?, ?, ?, ?, ?, 0.0)
        ''', (user_id, stock_id, quantity, stock['price'], total_cost, user['balance'], new_balance))
        
        conn.commit()
        log_event(
            30, #buy success
            f"Buy success: user {user_id} bought {quantity} shares of {stock['symbol']} at ${stock['price']:.2f} (total {total_cost:.2f}).",
            user_id=user_id
        )

        flash(f"Successfully bought {quantity} shares of {stock['symbol']} for ${total_cost:.2f}", "success")
        
    except Exception as e:
        conn.rollback()
        log_event(
            31, #buy failure
            f"Buy failed for user {user_id}: exception '{str(e)}'.",
            user_id=user_id
        )

        flash(f"Error buying stock: {str(e)}", "error")
    finally:
        conn.close()
    
    return redirect(url_for('dashboard', user_id=user_id))



@app.route('/sell_stock/<int:user_id>', methods=['POST'])
def sell_stock(user_id):
    if 'user_id' not in session or session['user_id'] != user_id:
        flash("Unauthorized.", "error")
        return redirect(url_for('login'))

    ms = get_market_status()
    if ms.get("status") != "open":
        next_open = ms.get("next_open")
        next_text = f" Next open: {next_open}." if next_open else ""
        flash(f"Market is closed: {ms.get('reason')}.{next_text}", "error")
        log_event(
            33, #sell failure
            f"Sell failed for user {user_id}: market closed ({ms.get('reason')}).",
            user_id=user_id
        )

        return redirect(url_for('dashboard', user_id=user_id))
        
    stock_id = int(request.form['stock_id'])
    quantity = int(request.form['quantity'])
    
    if quantity <= 0:
        flash("Quantity must be greater than zero.", "error")

        log_event(
            33, #sell failure
            f"Sell failed for user {user_id}: quantity <= 0.",
            user_id=user_id
        )

        return redirect(url_for('dashboard', user_id=user_id))
    
    conn = get_db_connection()
    
    try:
        user = conn.execute('SELECT * FROM users WHERE user_id = ?', (user_id,)).fetchone()
        stock = conn.execute('SELECT * FROM stocks WHERE stock_id = ?', (stock_id,)).fetchone()
        position = conn.execute(
            'SELECT * FROM portfolio WHERE user_id = ? AND stock_id = ?', 
            (user_id, stock_id)
        ).fetchone()
        
        if not user or not stock or not position:
            flash("User, stock, or position not found.", "error")
            log_event(
                33, #sell failure
                f"Sell failed for user {user_id}: user/stock/position missing.",
                user_id=user_id
            )

            return redirect(url_for('dashboard', user_id=user_id))
        
        if position['quantity'] < quantity:
            flash(f"Insufficient shares. Have {position['quantity']}, trying to sell {quantity}", "error")

            log_event(
                33, #sell failure
                f"Sell failed for user {user_id}: insufficient shares (had {position['quantity']}, wanted {quantity}).",
                user_id=user_id
            )

            return redirect(url_for('dashboard', user_id=user_id))
        
        total_value = quantity * stock['price']
        new_balance = user['balance'] + total_value
        
        cost_basis = quantity * position['avg_cost']
        realized_pl = total_value - cost_basis
        
        conn.execute('UPDATE users SET balance = ? WHERE user_id = ?', (new_balance, user_id))
        
        new_quantity = position['quantity'] - quantity
        if new_quantity > 0:
            new_total_invested = position['total_invested'] - cost_basis
            conn.execute('''
                UPDATE portfolio 
                SET quantity = ?, total_invested = ?, last_updated = CURRENT_TIMESTAMP
                WHERE user_id = ? AND stock_id = ?
            ''', (new_quantity, new_total_invested, user_id, stock_id))
        else:
            conn.execute('DELETE FROM portfolio WHERE user_id = ? AND stock_id = ?', (user_id, stock_id))
        
        conn.execute('''
            INSERT INTO orders (user_id, stock_id, order_type, quantity, price, cash_after, realized_pl)
            VALUES (?, ?, 'SELL', ?, ?, ?, ?)
        ''', (user_id, stock_id, quantity, stock['price'], new_balance, realized_pl))
        
        conn.execute('''
            INSERT INTO transaction_history 
            (user_id, stock_id, order_type, quantity, price, total_value, cash_before, cash_after, realized_pl)
            VALUES (?, ?, 'SELL', ?, ?, ?, ?, ?, ?)
        ''', (user_id, stock_id, quantity, stock['price'], total_value, user['balance'], new_balance, realized_pl))
        
        conn.commit()
        log_event(
            32, #sell success
            f"Sell success: user {user_id} sold {quantity} shares of {stock['symbol']} at ${stock['price']:.2f} (value {total_value:.2f}, P/L {realized_pl:.2f}).",
            user_id=user_id
        )

        pl_text = f" (P/L: ${realized_pl:.2f})" if realized_pl != 0 else ""
        flash(f"Successfully sold {quantity} shares of {stock['symbol']} for ${total_value:.2f}{pl_text}", "success")
        
    except Exception as e:
        conn.rollback()

        log_event(
            33, #sell failure
            f"Sell failed for user {user_id}: exception '{str(e)}'.",
            user_id=user_id
        )

        flash(f"Error selling stock: {str(e)}", "error")
    finally:
        conn.close()
    
    return redirect(url_for('dashboard', user_id=user_id))



# ----- admin routes (now protected) -----

@app.route('/admin')
def admin():
    check = require_admin()
    if check:
        return check

    conn = get_db_connection()

    # fetch all users for the table
    users = conn.execute(
        'SELECT user_id, username, email, balance FROM users'
    ).fetchall()

    # fetch current logged-in user for the "Logged in as" display
    current_user = conn.execute(
        "SELECT user_id, username FROM users WHERE user_id = ?",
        (session.get("user_id"),)
    ).fetchone()

    conn.close()

    return render_template(
        'admin.html',
        users=users,
        user=current_user  # <-- REQUIRED
    )



@app.route('/admin/users')
def admin_users():
    check = require_admin()
    if check:
        return check

    conn = get_db_connection()
    users = conn.execute('SELECT user_id, username, email, balance FROM users').fetchall()
    conn.close()
    return render_template('admin_users.html', users=users)
    
@app.route('/admin/user/<int:user_id>/edit', methods=['GET', 'POST'])
def admin_user_edit(user_id):
    check = require_admin()
    if check: 
        return check

    conn = get_db_connection()
    cursor = conn.cursor()

    # Fetch the user, including admin status
    user = cursor.execute(
        "SELECT user_id, username, email, is_admin FROM users WHERE user_id = ?",
        (user_id,)
    ).fetchone()

    if not user:
        conn.close()
        flash("User not found.", "error")
        return redirect(url_for('admin_users'))

    # Information about the currently logged-in admin
    current_admin_id = session.get("user_id")

    if request.method == "POST":
        new_username = request.form["username"].strip()
        new_email = request.form["email"].strip()
        requested_is_admin = 1 if request.form.get("is_admin") == "on" else 0

        old_username = user["username"]
        old_email = user["email"]
        old_is_admin = user["is_admin"]

        changes = []

        # Prevent lowering admins with equal/higher user_id
        if requested_is_admin < old_is_admin:
            if user_id <= current_admin_id:
                # Not permitted
                flash("You cannot remove admin status from users with equal or higher admin rank.", "error")
                conn.close()
                return redirect(url_for("admin_users"))

        # Attempt update
        try:
            cursor.execute("""
                UPDATE users
                SET username = ?, email = ?, is_admin = ?
                WHERE user_id = ?
            """, (new_username, new_email, requested_is_admin, user_id))

            conn.commit()

            # Track changes for logging
            if new_username != old_username:
                changes.append(f"username '{old_username}' → '{new_username}'")

            if new_email != old_email:
                changes.append(f"email '{old_email}' → '{new_email}'")

            if requested_is_admin != old_is_admin:
                if requested_is_admin == 1:
                    changes.append("admin status granted")
                else:
                    changes.append("admin status revoked")

            change_msg = ", ".join(changes) if changes else "No changes"

            # Build change log message
            changes = []

            if new_username != old_username:
                changes.append(f"username '{old_username}' → '{new_username}'")

            if new_email != old_email:
                changes.append(f"email '{old_email}' → '{new_email}'")

            if requested_is_admin != old_is_admin:
                if requested_is_admin == 1:
                    changes.append("admin status granted")
                else:
                    changes.append("admin status revoked")

            change_msg = ", ".join(changes) if changes else "No changes"

            log_event(
                48,  # Admin: User edited
                f"Admin edited user {user_id}: {change_msg}",
                user_id=current_admin_id
            )


            flash("User updated successfully!", "success")

        except sqlite3.IntegrityError:
            flash("Username or email already exists.", "error")

        conn.close()
        return redirect(url_for("admin_users"))

    # GET request → show page
    conn.close()
    return render_template(
        "admin_user_edit.html",
        user=user,
        current_admin_id=current_admin_id
    )


@app.route('/admin/user/<int:user_id>/portfolio')
def admin_user_portfolio(user_id):
    check = require_admin()
    if check:
        return check

    conn = get_db_connection()
    cursor = conn.cursor()

    # Pull new deposit/withdraw columns as well
    user = cursor.execute("""
        SELECT user_id, username, email, balance, total_deposited, total_withdrawn
        FROM users
        WHERE user_id = ?
    """, (user_id,)).fetchone()

    if not user:
        conn.close()
        flash("User not found.", "error")
        return redirect(url_for('admin_users'))

    portfolio = cursor.execute("""
        SELECT p.quantity, p.avg_cost, s.symbol, s.company_name
        FROM portfolio p
        JOIN stocks s ON p.stock_id = s.stock_id
        WHERE p.user_id = ?
    """, (user_id,)).fetchall()

    transactions = cursor.execute("""
        SELECT t.*, s.symbol
        FROM transaction_history t
        JOIN stocks s ON t.stock_id = s.stock_id
        WHERE t.user_id = ?
        ORDER BY timestamp DESC
    """, (user_id,)).fetchall()

    conn.close()
    return render_template(
        "admin_user_portfolio.html",
        user=user,
        portfolio=portfolio,
        transactions=transactions
    )


@app.route('/admin/user/<int:user_id>/delete', methods=['POST'])
def admin_user_delete(user_id):
    check = require_admin()
    if check: 
        return check

    # Prevent self-delete
    if user_id == session.get("user_id"):
        flash("You cannot delete your own account while logged in as admin.", "error")
        return redirect(url_for("admin_users"))

    conn = get_db_connection()
    cursor = conn.cursor()

    user = cursor.execute(
        "SELECT username FROM users WHERE user_id = ?",
        (user_id,)
    ).fetchone()

    if not user:
        conn.close()
        flash("User not found.", "error")
        return redirect(url_for('admin_users'))

    cursor.execute("DELETE FROM users WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()

    log_event(
        49,
        f"Admin deleted user '{user['username']}' (ID {user_id})",
        user_id=session.get("user_id")
    )

    flash("User deleted successfully.", "success")
    return redirect(url_for("admin_users"))




@app.route('/admin/stocks')
def admin_stocks():
    check = require_admin()
    if check:
        return check

    conn = get_db_connection()
    stocks = conn.execute('SELECT * FROM stocks').fetchall()
    conn.close()
    return render_template('admin_stocks.html', stocks=stocks)
    
@app.route('/admin/stocks/edit/<int:stock_id>', methods=['GET', 'POST'])
def admin_stock_edit(stock_id):
    check = require_admin()
    if check:
        return check

    conn = get_db_connection()
    stock = conn.execute('SELECT * FROM stocks WHERE stock_id = ?', (stock_id,)).fetchone()
    if not stock:
        conn.close()
        flash("Stock not found", "error")
        return redirect(url_for('admin_stocks'))

    if request.method == 'POST':
        symbol = request.form['symbol'].upper().strip()
        company_name = request.form['company_name'].strip()
        if not symbol or not company_name:
            flash("All fields are required", "error")
            return redirect(request.url)
        try:
            conn.execute('UPDATE stocks SET symbol = ?, company_name = ? WHERE stock_id = ?',
                         (symbol, company_name, stock_id))
            conn.commit()
            flash(f"Stock {symbol} updated successfully", "success")
            return redirect(url_for('admin_stocks'))
        except sqlite3.IntegrityError:
            flash("Symbol already exists", "error")
            return redirect(request.url)
    conn.close()
    return render_template('admin_stock_edit.html', stock=stock)



@app.route('/admin/stocks/delete/<int:stock_id>', methods=['POST'])
def admin_stock_delete(stock_id):
    check = require_admin()
    if check:
        return check

    conn = get_db_connection()
    conn.execute('DELETE FROM stocks WHERE stock_id = ?', (stock_id,))
    conn.commit()
    conn.close()
    flash("Stock deleted successfully", "success")
    return redirect(url_for('admin_stocks'))



@app.route('/admin/stock/create', methods=['GET', 'POST'])
def admin_stock_create():
    check = require_admin()
    if check:
        return check

    if request.method == 'POST':
        symbol = request.form['symbol'].upper()
        company_name = request.form['company_name']
        price = float(request.form['price'])
        
        conn = get_db_connection()
        try:
            conn.execute(
                'INSERT INTO stocks (symbol, company_name, price) VALUES (?, ?, ?)',
                (symbol, company_name, price)
            )
            conn.commit()
            flash(f"Stock {symbol} created successfully!", "success")

            log_event(
                43,  # Admin: Stock Created
                f"Admin created stock '{symbol}' ({company_name}) with price {price}.",
                user_id=session.get('user_id')
            )

            return redirect(url_for('admin_stocks'))
        except sqlite3.IntegrityError:
            flash("Stock symbol already exists.", "error")
            log_event(
                44,  # Admin: Stock Creation Failed
                f"Admin attempted to create stock '{symbol}' but symbol exists.",
                user_id=session.get('user_id')
            )
        finally:
            conn.close()
    
    return render_template('admin_stock_create.html')



@app.route('/admin/stock/update', methods=['GET', 'POST'])
def admin_stock_update():
    check = require_admin()
    if check:
        return check

    conn = get_db_connection()
    stocks = conn.execute('SELECT * FROM stocks').fetchall()
    
    if request.method == 'POST':
        stock_id = request.form['stock_id']
        new_price = float(request.form['new_price'])
        
        conn.execute(
            'UPDATE stocks SET price = ? WHERE stock_id = ?',
            (new_price, stock_id)
        )
        conn.commit()
        flash("Stock price updated successfully!", "success")
        return redirect(url_for('admin_stock_update'))
    
    conn.close()
    return render_template('admin_stock_update.html', stocks=stocks)


@app.route('/admin/market/hours', methods=['GET', 'POST'])
def admin_market_hours():
    check = require_admin()
    if check: 
        return check

    if request.method == 'POST':
        conn = get_db_connection()
        conn.execute("""
            UPDATE market_schedule
            SET open_time = ?, close_time = ?, timezone = ?
            WHERE id = 1
        """, (
            request.form['open_time'],
            request.form['close_time'],
            request.form['timezone'],
        ))
        conn.commit()
        conn.close()

        flash("Market hours updated.", "success")

        log_event(
            46,  # Admin: Market Hours Updated
            f"Admin updated market hours to {request.form['open_time']}–{request.form['close_time']} {request.form['timezone']}.",
            user_id=session.get('user_id')
        )

        return redirect(url_for('admin_market_hours'))

    settings = get_market_schedule()
    return render_template('admin_market_hours.html', settings=settings)


@app.route("/admin/market/schedule", methods=["GET", "POST"])
def admin_market_schedule():
    check = require_admin()
    if check:
        return check

    conn = get_db_connection()

    # Retrieve or initialize schedule
    settings = get_market_schedule()
    if settings is None:
        conn.execute("""
            INSERT INTO market_schedule
            (open_time, close_time, timezone, trading_days, holidays, manual_override, manual_message)
            VALUES ('09:30', '16:00', 'EST', 'monday,tuesday,wednesday,thursday,friday', '', 0, '')
        """)
        conn.commit()
        settings = get_market_schedule()

    if request.method == "POST":

        # Collect day checkboxes
        all_days = ["monday","tuesday","wednesday","thursday","friday","saturday","sunday"]
        selected_days = [d for d in all_days if request.form.get(f"day_{d}") == d]

        holidays = request.form.get("holidays", "").strip()

        # manual override fields
        manual_override = 1 if request.form.get("manual_override") == "on" else 0
        manual_message = request.form.get("manual_message", "").strip()

        # UPDATE the full schedule at once
        conn.execute("""
            UPDATE market_schedule
            SET trading_days = ?, holidays = ?, manual_override = ?, manual_message = ?
        """, (
            ",".join(selected_days),
            holidays,
            manual_override,
            manual_message
        ))

        conn.commit()
        conn.close()

        # Flash message
        flash("Market schedule updated!", "success")

        readable_override = "ON" if manual_override else "OFF"
        log_event(
            47, #Market Schedule Updated
            f"Admin updated schedule: days={','.join(selected_days)}, holidays={holidays or 'none'}, "
            f"override={readable_override}, msg='{manual_message or 'none'}'.",
            user_id=session.get("user_id")
        )

        return redirect(url_for("admin_market_schedule"))

    conn.close()

    # Parse active days list for template
    active_days = settings["trading_days"].split(",") if settings["trading_days"] else []
    all_days = ["monday","tuesday","wednesday","thursday","friday","saturday","sunday"]

    return render_template(
        "admin_market_schedule.html",
        settings=settings,
        active_days=active_days,
        days=all_days
    )


    conn.close()
    active_days = settings["trading_days"].split(",") if settings["trading_days"] else []
    all_days = ["monday","tuesday","wednesday","thursday","friday","saturday","sunday"]

    return render_template(
        "admin_market_schedule.html",
        settings=settings,
        active_days=active_days,
        days=all_days
    )


    
@app.route('/admin/market/logs')
def admin_logs():
    check = require_admin()
    if check:
        return check

    page = int(request.args.get('page', 1))
    per_page = int(request.args.get('per_page', 10))

    # Multi-select types
    selected_types = request.args.getlist("type")  # list of strings

    conn = get_db_connection()

    # Base query
    base_query = "FROM logs"
    params = []

    # Filtering
    if selected_types:
        placeholders = ",".join("?" for _ in selected_types)
        base_query += f" WHERE type IN ({placeholders})"
        params.extend(int(t) for t in selected_types)

    # Count logs
    count_query = "SELECT COUNT(*) " + base_query
    total_logs = conn.execute(count_query, params).fetchone()[0]

    # Pagination
    offset = (page - 1) * per_page
    log_query = (
        "SELECT * " + base_query +
        " ORDER BY timestamp DESC LIMIT ? OFFSET ?"
    )

    logs = conn.execute(log_query, params + [per_page, offset]).fetchall()
    conn.close()

    event_types = {
        1: "Successful Login",
        2: "Failed Login",
        3: "Logout",
        4: "Account Registered",
        10: "Deposit",
        11: "Withdrawal",
        30: "Buy order succeeded",
        31: "Buy order failed",
        32: "Sell order succeeded",
        33: "Sell order failed",
        41: "Admin: Logs Downloaded",
        42: "Admin: Logs Cleared",
        43: "Admin: Stock Created",
        44: "Admin: Stock Creation Failed",
        45: "Admin: Stock Price Updated",
        46: "Admin: Market Hours Updated",
        47: "Admin: Market Schedule Updated",
        48: "Admin: User edited",
        49: "Admin: User deleted",
        50: "Stock price generator settings updated"
    }

    total_pages = (total_logs + per_page - 1) // per_page

    return render_template(
        'admin_logs.html',
        logs=logs,
        page=page,
        per_page=per_page,
        total_pages=total_pages,
        event_types=event_types,
        selected_types=selected_types  # pass list
    )


@app.route('/admin/market/logs/download')
def admin_logs_download():
    check = require_admin()
    if check:
        return check

    conn = get_db_connection()
    logs = conn.execute("SELECT * FROM logs ORDER BY timestamp DESC").fetchall()
    conn.close()

    # Convert logs to CSV string
    import csv
    from io import StringIO

    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(["log_id", "type", "details", "user_id", "timestamp"])

    for log in logs:
        writer.writerow([log["log_id"], log["type"], log["details"], log["user_id"], log["timestamp"]])

    csv_data = output.getvalue()
    output.close()

    log_event(
        41, #Logs Downloaded
        "Admin downloaded a complete copy of the logs.",
        user_id=session.get("user_id")
    )

    # Send the CSV file
    from flask import Response
    return Response(
        csv_data,
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment;filename=equisense_logs.csv"}
    )

@app.route('/admin/market/logs/clear', methods=['POST'])
def admin_logs_clear():
    check = require_admin()
    if check:
        return check

    conn = get_db_connection()
    cursor = conn.cursor()

    # Clear logs
    cursor.execute("DELETE FROM logs")
    conn.commit()

    # Insert new log AFTER clearing (fresh table)
    log_event(
        42,
        "Admin cleared all logs.",
        user_id=session.get("user_id")
    )

    flash("All logs have been cleared.", "success")
    return redirect(url_for('admin_logs'))


@app.route('/admin/settings', methods=['GET', 'POST'])
def admin_settings():
    check = require_admin()
    if check:
        return check

    conn = get_db_connection()
    cursor = conn.cursor()

    # Load current settings
    settings = get_generator_settings()

    if request.method == "POST":
    
        # Extract new values from form
        enabled = 1 if request.form.get("enabled") == "on" else 0
        interval_seconds = int(request.form.get("interval_seconds", 10))
        volatility = float(request.form.get("volatility", 0.005))
        trend_bias = float(request.form.get("trend_bias", 0.0002))
        exaggeration = float(request.form.get("exaggeration", 1.0))

        # Track changes for logging
        changes = []
        def compare(field, old, new):
            if float(old) != float(new):
                changes.append(f"{field}: {old} → {new}")

        compare("enabled", settings["enabled"], enabled)
        compare("interval_seconds", settings["interval_seconds"], interval_seconds)
        compare("volatility", settings["volatility"], volatility)
        compare("trend_bias", settings["trend_bias"], trend_bias)
        compare("exaggeration", settings["exaggeration"], exaggeration)

        # Update DB
        cursor.execute("""
            UPDATE price_generator_settings
            SET enabled = ?, interval_seconds = ?, volatility = ?, trend_bias = ?, exaggeration = ?
            WHERE id = 1
        """, (enabled, interval_seconds, volatility, trend_bias, exaggeration))
        conn.commit()

        # Log changes
        if changes:
            log_event(
                50,
                "Generator settings updated: " + "; ".join(changes),
                user_id=session.get("user_id")
            )

        flash("Settings updated successfully!", "success")
        conn.close()
        return redirect(url_for("admin_settings"))

    # GET request
    conn.close()
    return render_template("admin_settings.html", settings=settings)


def get_market_schedule():
    conn = get_db_connection()
    schedule = conn.execute(
        "SELECT * FROM market_schedule ORDER BY id DESC LIMIT 1"
    ).fetchone()
    conn.close()
    return schedule

def compute_next_open(schedule, from_dt=None):
    """
    Look forward up to 30 days for the next datetime when the market will open.
    Returns timestamp string or None.
    """
    if not schedule:
        return None

    if from_dt is None:
        from_dt = datetime.now()

    open_time = schedule["open_time"]
    trading_days = (schedule["trading_days"] or "").split(",")
    holidays_raw = schedule["holidays"] or ""

    # Normalize holiday list
    holidays = [h.strip() for h in holidays_raw.split("\n") if h.strip()]

    def is_holiday(date_obj):
        mmdd = date_obj.strftime("%m-%d")
        iso = date_obj.strftime("%Y-%m-%d")
        for h in holidays:
            prefix = h.split("-", 1)[0].strip()
            if prefix == mmdd or prefix == iso:
                return True
        return False

    # Parse open time
    try:
        open_h, open_m = [int(x) for x in open_time.split(":")]
    except:
        open_h, open_m = 9, 30  # fallback

    for i in range(0, 31):
        day = from_dt + timedelta(days=i)
        weekday_name = day.strftime("%A").lower()

        # Check day-of-week
        if weekday_name not in trading_days:
            continue

        # Holiday check
        if is_holiday(day):
            continue

        # Candidate open time
        open_dt = day.replace(hour=open_h, minute=open_m, second=0, microsecond=0)

        if open_dt > from_dt:
            return open_dt.strftime("%Y-%m-%d %H:%M:%S")

    return None

def get_market_status():
    """
    Returns:
    {
        "status": "open" | "closed",
        "reason": "...",
        "next_open": "YYYY-MM-DD HH:MM:SS" or None
    }
    """
    schedule = get_market_schedule()
    if not schedule:
        return {"status": "closed", "reason": "No schedule configured", "next_open": None}

    # 1. MANUAL OVERRIDE
    if schedule["manual_override"]:
        msg = schedule["manual_message"] or "Market manually closed"
        next_open = compute_next_open(schedule)

        return {
            "status": "closed",
            "reason": f"Manual override: {msg}",
            "next_open": next_open
        }

    # 2. NORMAL SCHEDULE CHECKS
    now = datetime.now()
    weekday = now.strftime("%A").lower()
    now_time_str = now.strftime("%H:%M")

    trading_days = (schedule["trading_days"] or "").split(",")
    holidays_raw = schedule["holidays"] or ""

    # Parse each holiday line into its date field
    holidays = [h.strip() for h in holidays_raw.split("\n") if h.strip()]
    mmdd = now.strftime("%m-%d")

    # 3. HOLIDAY CHECK
    for h in holidays:
        date_part = h.split(" - ")[0].strip()  # "MM-DD"
        if date_part == mmdd:
            next_open = compute_next_open(schedule)
            return {
                "status": "closed",
                "reason": f"Market closed for holiday: {h}",
                "next_open": next_open
            }

    # 4. TRADING DAY CHECK
    if weekday not in trading_days:
        next_open = compute_next_open(schedule)
        return {
            "status": "closed",
            "reason": f"Market closed today ({weekday.title()})",
            "next_open": next_open
        }

    # 5. TIME WINDOW CHECK
    open_time = schedule["open_time"]
    close_time = schedule["close_time"]

    if not (open_time <= now_time_str <= close_time):
        # Determine next open time
        try:
            if now_time_str < open_time:
                # Will open later today
                h, m = map(int, open_time.split(":"))
                next_open_dt = now.replace(hour=h, minute=m, second=0, microsecond=0)
                next_open = next_open_dt.strftime("%Y-%m-%d %H:%M:%S")
            else:
                # Opens next valid day
                next_open = compute_next_open(schedule)
        except:
            next_open = compute_next_open(schedule)

        return {
            "status": "closed",
            "reason": f"Market closed at this time (open {open_time}–{close_time})",
            "next_open": next_open
        }

    # 6. MARKET IS OPEN
    return {
        "status": "open",
        "reason": "Market is open",
        "next_open": None
    }


@app.route("/api/market/status")
def api_market_status():
    status = get_market_status()
    return jsonify(status)

def log_event(event_type, details, user_id=None):
    """
    Logs an event to the logs table.

    :param event_type: Integer representing event category/type
    :param details: Text description of the event
    :param user_id: Optional user ID (None for system events)
    """

    for _ in range(8):  # retry up to 8 times on locked DB
        try:
            conn = get_db_connection()
            cur = conn.cursor()

            timestamp = datetime.utcnow().isoformat()

            cur.execute("""
                INSERT INTO logs (type, details, timestamp, user_id)
                VALUES (?, ?, ?, ?)
            """, (event_type, details, timestamp, user_id))

            conn.commit()
            conn.close()
            return  # success
        except sqlite3.OperationalError as e:
            if "locked" in str(e).lower():
                time.sleep(0.05)
                continue
            raise  # real error → raise immediately

    print("log_event FAILED after all retries!")


#stuff for the price generator

def get_generator_settings():
    conn = get_db_connection()
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM price_generator_settings WHERE id = 1").fetchone()
    conn.close()

    if not row:
        # initialize settings if they don't exist
        conn = get_db_connection()
        conn.execute("""
            INSERT INTO price_generator_settings (id, enabled, interval_seconds, volatility, trend_bias)
            VALUES (1, 1, 10, 0.01, 0.0)
        """)
        conn.commit()
        conn.close()
        return get_generator_settings()

    return row

def apply_price_change(old_price, volatility, trend_bias):
    """
    Generate a new stock price using Gaussian noise.
    
    - volatility = standard deviation of returns (e.g. 0.01 = 1%)
    - trend_bias = average directional drift (e.g. 0.0005 for slight upward trend)

    Price model:
        new_price = old_price * exp( GaussianNoise + trend_bias )
    """
    # Gaussian noise, centered at 0
    gaussian_return = random.gauss(mu=0, sigma=volatility)

    # Add drift
    total_return = gaussian_return + trend_bias

    # Compute new price using log-normal model
    new_price = old_price * math.exp(total_return)

    # Avoid negative or zero price
    if new_price < 0.01:
        new_price = 0.01

    return round(new_price, 2)
    
def safe_execute(query, params=()):
    for _ in range(5):  # retry up to 5 times
        try:
            conn = get_db_connection()
            conn.execute(query, params)
            conn.commit()
            conn.close()
            return
        except sqlite3.OperationalError as e:
            if "locked" in str(e).lower():
                time.sleep(0.1)  # small delay then retry
            else:
                raise
    print("DB write failed after retries:", query)

def update_all_stock_prices():
    settings = get_generator_settings()

    if not settings["enabled"]:
        return

    volatility = settings["volatility"]
    trend_bias = settings["trend_bias"]

    # GET STOCK LIST WITH ONE CONNECTION
    conn = get_db_connection()
    conn.row_factory = sqlite3.Row
    stocks = conn.execute("SELECT stock_id, price FROM stocks").fetchall()
    conn.close()

    # PROCESS EACH STOCK USING safe_execute (each has its own conn)
    for stock in stocks:
        new_price = apply_price_change(stock["price"], volatility, trend_bias)

        # update main price
        safe_execute(
            "UPDATE stocks SET price = ? WHERE stock_id = ?",
            (new_price, stock["stock_id"])
        )

        # update history
        safe_execute(
            "INSERT INTO price_history (stock_id, price) VALUES (?, ?)",
            (stock["stock_id"], new_price)
        )


def price_generator_loop():
    print("Price generator loop initiated")
    while True:
        try:
            settings = get_generator_settings()
            interval = settings["interval_seconds"]
            update_all_stock_prices()
            time.sleep(interval)
        except Exception as e:
            print("Generator crashed:", e)
            time.sleep(10)

#start background threat for price generator
thread = Thread(target=price_generator_loop, daemon=True)
thread.start()

# run the flask app
if __name__ == '__main__': 
    app.run(debug=True, port=5000)

