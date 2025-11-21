import os
from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify
from datetime import datetime, timedelta
import sqlite3
import bcrypt
import json

app = Flask(__name__)

app.secret_key = 'team34' # needed for flash messages and session management
#app.secret_key = os.environ.get("FLASK_SECRET_KEY", "dev_default_key") this should be used in the deployed version of the app

DB_NAME = 'stock_trading.db'

# connect to the database
def get_db_connection():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
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



# register new user
@app.route('/register', methods=['POST'])
def register():
    username = request.form['username']
    email = request.form['email']
    password = request.form['password']

    password_hash = hash_password(password)

    conn = get_db_connection()
    try:
        conn.execute(
            'INSERT INTO users (username, email, password_hash, balance) VALUES (?, ?, ?, ?)',
            (username, email, password_hash, 0.0)
        )
        conn.commit()
        log_event(
             4,  # Account Registered
             f"User account '{username}' created.",
             user_id = cursor.lastrowid
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


# user dashboard
@app.route('/dashboard/<int:user_id>')
def dashboard(user_id):
    # Require login
    if 'user_id' not in session or session['user_id'] != user_id:
        flash("You must be logged in to view that page.", "error")
        return redirect(url_for('login'))

    conn = get_db_connection()
    user = conn.execute('SELECT * FROM users WHERE user_id = ?', (user_id,)).fetchone()

    if not user:
        flash("User not found.", "error")
        conn.close()
        return redirect(url_for('login'))

    # Get available stocks (all stocks in the system)
    available_stocks = conn.execute('SELECT * FROM stocks ORDER BY symbol').fetchall()
    
    # Get user's portfolio with detailed information
    portfolio = conn.execute('''
        SELECT s.stock_id, s.symbol, s.company_name, s.price as current_price,
               p.quantity, p.avg_cost, p.total_invested,
               (p.quantity * s.price) AS value,
               (s.price - p.avg_cost) * p.quantity AS unrealized_pl
        FROM portfolio p
        JOIN stocks s ON p.stock_id = s.stock_id
        WHERE p.user_id = ? AND p.quantity > 0
        ORDER BY s.symbol
    ''', (user_id,)).fetchall()
    
    # Get transaction history
    transaction_history = conn.execute('''
        SELECT th.*, s.symbol
        FROM transaction_history th
        JOIN stocks s ON th.stock_id = s.stock_id
        WHERE th.user_id = ?
        ORDER BY th.timestamp DESC
        LIMIT 50
    ''', (user_id,)).fetchall()
    
    conn.close()

    return render_template(
        'dashboard.html',
        user=user,
        balance=user['balance'],
        portfolio=portfolio,
        available_stocks=available_stocks,
        transaction_history=transaction_history,
        user_id=user_id
    )

# unified deposit/withdraw (so they can share an input field)
@app.route('/depositwithdraw/<int:user_id>', methods=['POST'])
def depositwithdraw(user_id):
    if 'user_id' not in session or session['user_id'] != user_id:
        flash("Unauthorized.", "error")
        return redirect(url_for('login'))

    amount = float(request.form['amount'])
    action = request.form['action']

    if amount <= 0:
        flash("Amount must be greater than zero.", "error")
        return redirect(url_for('dashboard', user_id=user_id))

    conn = get_db_connection()
    user = conn.execute('SELECT balance FROM users WHERE user_id = ?', (user_id,)).fetchone()

    if not user:
        flash("User not found.", "error")
        conn.close()
        return redirect(url_for('login'))

    balance = user['balance']

    if action == 'deposit':
        conn.execute('UPDATE users SET balance = balance + ? WHERE user_id = ?', (amount, user_id))

        log_event(
            10,  # deposit event
            f"User {user_id} deposited ${amount:.2f}.",
            user_id=user_id
        )

        flash(f"Deposited ${amount:.2f}.", "success")

    elif action == 'withdraw':
        if balance < amount:
            flash("Insufficient funds.", "error")
            conn.close()
            return redirect(url_for('dashboard', user_id=user_id))

        conn.execute('UPDATE users SET balance = balance - ? WHERE user_id = ?', (amount, user_id))

        log_event(
            11,  # withdraw event
            f"User {user_id} withdrew ${amount:.2f}.",
            user_id=user_id
        )

        flash(f"Withdrew ${amount:.2f}.", "success")

    conn.commit()
    conn.close()
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
    users = conn.execute('SELECT user_id, username, email, balance FROM users').fetchall()
    conn.close()

    return render_template('admin.html', users=users)


@app.route('/admin/users')
def admin_users():
    check = require_admin()
    if check:
        return check

    conn = get_db_connection()
    users = conn.execute('SELECT user_id, username, email, balance FROM users').fetchall()
    conn.close()
    return render_template('admin_users.html', users=users)


@app.route('/admin/user/create', methods=['GET', 'POST'])
def admin_user_create():
    check = require_admin()
    if check:
        return check

    if request.method == 'POST':
        username = request.form['username']
        email = request.form['email']
        balance = float(request.form.get('balance', 0.0))
        
        conn = get_db_connection()
        try:
            conn.execute(
                'INSERT INTO users (username, email, balance) VALUES (?, ?, ?)',
                (username, email, balance)
            )
            conn.commit()
            flash("User created successfully!", "success")
            
            # Log creation
            log_event(
                41,  # Admin: User Created
                f"Admin created user '{username}' with balance {balance}.",
                user_id=session.get('user_id')
            )

            return redirect(url_for('admin_users'))
        except sqlite3.IntegrityError:
            flash("Username or email already exists.", "error")
            log_event(
                42,  # Admin: User Creation Failed
                f"Admin attempted to create user '{username}' but username/email exists.",
                user_id=session.get('user_id')
            )
        finally:
            conn.close()
    
    return render_template('admin_user_create.html')


@app.route('/admin/stocks')
def admin_stocks():
    check = require_admin()
    if check:
        return check

    conn = get_db_connection()
    stocks = conn.execute('SELECT * FROM stocks').fetchall()
    conn.close()
    return render_template('admin_stocks.html', stocks=stocks)


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
        all_days = ["monday","tuesday","wednesday","thursday","friday","saturday","sunday"]
        selected_days = [d for d in all_days if request.form.get(f"day_{d}") == d]
        holidays = request.form.get("holidays", "").strip()

        conn.execute("""
            UPDATE market_schedule
            SET trading_days = ?, holidays = ?
        """, (",".join(selected_days), holidays))
        conn.commit()
        conn.close()

        flash("Market schedule updated!", "success")

        log_event(
            47,  # Admin: Market Schedule Updated
            f"Admin updated market schedule: trading days {','.join(selected_days)}, holidays: {holidays or 'none'}.",
            user_id=session.get('user_id')
        )

        return redirect(url_for("admin_market_schedule"))

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

    # Pagination parameters
    page = int(request.args.get('page', 1))
    per_page = int(request.args.get('per_page', 10))
    selected_type = request.args.get('type', 'all')

    conn = get_db_connection()

    # Base query
    query = "SELECT * FROM logs"
    params = []

    # Filter by event type if selected
    if selected_type != 'all':
        query += " WHERE type = ?"
        params.append(int(selected_type))

    # Count total entries for pagination
    total_logs = conn.execute(query.replace('*', 'COUNT(*)'), params).fetchone()[0]

    # Apply limit/offset for pagination
    offset = (page - 1) * per_page
    query += " ORDER BY timestamp DESC LIMIT ? OFFSET ?"
    params.extend([per_page, offset])

    logs = conn.execute(query, params).fetchall()
    conn.close()

    # Event type map for filter dropdown
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
        41: "Admin: User Created",
        42: "Admin: User Creation Failed",
        43: "Admin: Stock Created",
        44: "Admin: Stock Creation Failed",
        45: "Admin: Stock Price Updated",
        46: "Admin: Market Hours Updated",
        47: "Admin: Market Schedule Updated"
    }

    total_pages = (total_logs + per_page - 1) // per_page

    return render_template(
        'admin_logs.html',
        logs=logs,
        page=page,
        per_page=per_page,
        total_pages=total_pages,
        event_types=event_types,
        selected_type=selected_type
    )


@app.route('/admin/settings')
def admin_settings():
    check = require_admin()
    if check:
        return check

    return render_template('admin_settings.html')

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

    # Manual override
    if schedule["manual_override"]:
        msg = schedule["manual_message"] or "Market manually closed"
        next_open = compute_next_open(schedule)
        return {
            "status": "closed",
            "reason": f"Manual override: {msg}",
            "next_open": next_open
        }

    now = datetime.now()
    weekday = now.strftime("%A").lower()
    now_time_str = now.strftime("%H:%M")

    # Parse schedule fields
    trading_days = (schedule["trading_days"] or "").split(",")
    holidays_raw = schedule["holidays"] or ""
    holidays = [h.strip() for h in holidays_raw.split("\n") if h.strip()]

    # Check if today is a holiday
    mmdd = now.strftime("%m-%d")
    for h in holidays:
        date_part = h.split(" - ")[0].strip()  # Extract "MM-DD" from "MM-DD - description"
    if date_part == mmdd:
        next_open = compute_next_open(schedule)
        return {
            "status": "closed",
            "reason": f"Market closed for holiday: {h}",
            "next_open": next_open
        }


    # Check if today is a trading day
    if weekday not in trading_days:
        next_open = compute_next_open(schedule)
        return {
            "status": "closed",
            "reason": f"Market closed today ({weekday.title()})",
            "next_open": next_open
        }

    # Time window
    open_time = schedule["open_time"]
    close_time = schedule["close_time"]

    if not (open_time <= now_time_str <= close_time):
        next_open = None
        try:
            # If we haven't yet reached open_time today
            if now_time_str < open_time:
                h, m = [int(x) for x in open_time.split(":")]
                next_open_dt = now.replace(hour=h, minute=m, second=0, microsecond=0)
                next_open = next_open_dt.strftime("%Y-%m-%d %H:%M:%S")
            else:
                next_open = compute_next_open(schedule)
        except:
            next_open = compute_next_open(schedule)

        return {
            "status": "closed",
            "reason": f"Market closed at this time (open {open_time}–{close_time})",
            "next_open": next_open
        }

    # Otherwise it's open
    return {"status": "open", "reason": "Market is open", "next_open": None}

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

    conn = get_db_connection()
    cur = conn.cursor()

    timestamp = datetime.utcnow().isoformat()

    cur.execute("""
        INSERT INTO logs (type, details, timestamp, user_id)
        VALUES (?, ?, ?, ?)
    """, (event_type, details, timestamp, user_id))

    conn.commit()
    conn.close()


# run the flask app
if __name__ == '__main__':
    app.run(debug=True, port=5000)
