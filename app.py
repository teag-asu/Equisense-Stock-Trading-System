from flask import Flask, render_template, request, redirect, url_for, flash
import sqlite3

app = Flask(__name__)
app.secret_key = 'team34'  # needed for flash messages and session management

DB_NAME = 'stock_trading.db'

# connect to the database
def get_db_connection():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn


# home / login Page
@app.route('/')
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        email = request.form['email']

        conn = get_db_connection()
        user = conn.execute(
            'SELECT * FROM users WHERE username = ? AND email = ?',
            (username, email)
        ).fetchone()
        conn.close()

        if user:
            flash(f"Welcome back, {user['username']}!", "success")
            return redirect(url_for('dashboard', user_id=user['user_id']))
        else:
            flash("Invalid credentials or user not found.", "error")
            return redirect(url_for('login'))

    return render_template('login.html')


# register new user
@app.route('/register', methods=['POST'])
def register():
    username = request.form['username']
    email = request.form['email']

    conn = get_db_connection()
    try:
        conn.execute(
            'INSERT INTO users (username, email, balance) VALUES (?, ?, ?)',
            (username, email, 0.0)
        )
        conn.commit()
        flash("Account created successfully! Please log in.", "success")
    except sqlite3.IntegrityError:
        flash("Username or email already exists.", "error")
    finally:
        conn.close()

    return redirect(url_for('login'))


# user dashboard
@app.route('/dashboard/<int:user_id>')
def dashboard(user_id):
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


# deposit function
@app.route('/deposit/<int:user_id>', methods=['POST'])
def deposit(user_id):
    amount = float(request.form['amount'])
    if amount <= 0:
        flash("Deposit amount must be greater than zero.", "error")
        return redirect(url_for('dashboard', user_id=user_id))

    conn = get_db_connection()
    conn.execute(
        'UPDATE users SET balance = balance + ? WHERE user_id = ?',
        (amount, user_id)
    )
    conn.commit()
    conn.close()

    flash(f"Successfully deposited ${amount:.2f}.", "success")
    return redirect(url_for('dashboard', user_id=user_id))


# withdraw function
@app.route('/withdraw/<int:user_id>', methods=['POST'])
def withdraw(user_id):
    amount = float(request.form['amount'])
    if amount <= 0:
        flash("Withdrawal amount must be greater than zero.", "error")
        return redirect(url_for('dashboard', user_id=user_id))

    conn = get_db_connection()
    user = conn.execute('SELECT balance FROM users WHERE user_id = ?', (user_id,)).fetchone()

    if not user:
        conn.close()
        flash("User not found.", "error")
        return redirect(url_for('login'))

    if user['balance'] < amount:
        conn.close()
        flash("Insufficient funds for this withdrawal.", "error")
        return redirect(url_for('dashboard', user_id=user_id))

    conn.execute(
        'UPDATE users SET balance = balance - ? WHERE user_id = ?',
        (amount, user_id)
    )
    conn.commit()
    conn.close()

    flash(f"Successfully withdrew ${amount:.2f}.", "success")
    return redirect(url_for('dashboard', user_id=user_id))


# buy stock function
@app.route('/buy_stock/<int:user_id>', methods=['POST'])
def buy_stock(user_id):
    stock_id = int(request.form['stock_id'])
    quantity = int(request.form['quantity'])
    
    if quantity <= 0:
        flash("Quantity must be greater than zero.", "error")
        return redirect(url_for('dashboard', user_id=user_id))
    
    conn = get_db_connection()
    
    try:
        # Get user and stock information
        user = conn.execute('SELECT * FROM users WHERE user_id = ?', (user_id,)).fetchone()
        stock = conn.execute('SELECT * FROM stocks WHERE stock_id = ?', (stock_id,)).fetchone()
        
        if not user or not stock:
            flash("User or stock not found.", "error")
            return redirect(url_for('dashboard', user_id=user_id))
        
        total_cost = quantity * stock['price']
        
        # Check if user has enough cash
        if user['balance'] < total_cost:
            flash(f"Insufficient funds. Need ${total_cost:.2f}, have ${user['balance']:.2f}", "error")
            return redirect(url_for('dashboard', user_id=user_id))
        
        # Update user balance
        new_balance = user['balance'] - total_cost
        conn.execute('UPDATE users SET balance = ? WHERE user_id = ?', (new_balance, user_id))
        
        # Check if user already has this stock
        existing_position = conn.execute(
            'SELECT * FROM portfolio WHERE user_id = ? AND stock_id = ?', 
            (user_id, stock_id)
        ).fetchone()
        
        if existing_position:
            # Update existing position (calculate new average cost)
            new_quantity = existing_position['quantity'] + quantity
            new_total_invested = existing_position['total_invested'] + total_cost
            new_avg_cost = new_total_invested / new_quantity
            
            conn.execute('''
                UPDATE portfolio 
                SET quantity = ?, avg_cost = ?, total_invested = ?, last_updated = CURRENT_TIMESTAMP
                WHERE user_id = ? AND stock_id = ?
            ''', (new_quantity, new_avg_cost, new_total_invested, user_id, stock_id))
        else:
            # Create new position
            conn.execute('''
                INSERT INTO portfolio (user_id, stock_id, quantity, avg_cost, total_invested, last_updated)
                VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ''', (user_id, stock_id, quantity, stock['price'], total_cost))
        
        # Record the order
        conn.execute('''
            INSERT INTO orders (user_id, stock_id, order_type, quantity, price, cash_after)
            VALUES (?, ?, 'BUY', ?, ?, ?)
        ''', (user_id, stock_id, quantity, stock['price'], new_balance))
        
        # Record transaction history
        conn.execute('''
            INSERT INTO transaction_history 
            (user_id, stock_id, order_type, quantity, price, total_value, cash_before, cash_after, realized_pl)
            VALUES (?, ?, 'BUY', ?, ?, ?, ?, ?, 0.0)
        ''', (user_id, stock_id, quantity, stock['price'], total_cost, user['balance'], new_balance))
        
        conn.commit()
        flash(f"Successfully bought {quantity} shares of {stock['symbol']} for ${total_cost:.2f}", "success")
        
    except Exception as e:
        conn.rollback()
        flash(f"Error buying stock: {str(e)}", "error")
    finally:
        conn.close()
    
    return redirect(url_for('dashboard', user_id=user_id))


# sell stock function
@app.route('/sell_stock/<int:user_id>', methods=['POST'])
def sell_stock(user_id):
    stock_id = int(request.form['stock_id'])
    quantity = int(request.form['quantity'])
    
    if quantity <= 0:
        flash("Quantity must be greater than zero.", "error")
        return redirect(url_for('dashboard', user_id=user_id))
    
    conn = get_db_connection()
    
    try:
        # Get user and stock information
        user = conn.execute('SELECT * FROM users WHERE user_id = ?', (user_id,)).fetchone()
        stock = conn.execute('SELECT * FROM stocks WHERE stock_id = ?', (stock_id,)).fetchone()
        position = conn.execute(
            'SELECT * FROM portfolio WHERE user_id = ? AND stock_id = ?', 
            (user_id, stock_id)
        ).fetchone()
        
        if not user or not stock or not position:
            flash("User, stock, or position not found.", "error")
            return redirect(url_for('dashboard', user_id=user_id))
        
        # Check if user has enough shares
        if position['quantity'] < quantity:
            flash(f"Insufficient shares. Have {position['quantity']}, trying to sell {quantity}", "error")
            return redirect(url_for('dashboard', user_id=user_id))
        
        total_value = quantity * stock['price']
        new_balance = user['balance'] + total_value
        
        # Calculate realized P/L
        cost_basis = (quantity * position['avg_cost'])
        realized_pl = total_value - cost_basis
        
        # Update user balance
        conn.execute('UPDATE users SET balance = ? WHERE user_id = ?', (new_balance, user_id))
        
        # Update or remove position
        new_quantity = position['quantity'] - quantity
        if new_quantity > 0:
            # Update position
            new_total_invested = position['total_invested'] - cost_basis
            conn.execute('''
                UPDATE portfolio 
                SET quantity = ?, total_invested = ?, last_updated = CURRENT_TIMESTAMP
                WHERE user_id = ? AND stock_id = ?
            ''', (new_quantity, new_total_invested, user_id, stock_id))
        else:
            # Remove position completely
            conn.execute('DELETE FROM portfolio WHERE user_id = ? AND stock_id = ?', (user_id, stock_id))
        
        # Record the order
        conn.execute('''
            INSERT INTO orders (user_id, stock_id, order_type, quantity, price, cash_after, realized_pl)
            VALUES (?, ?, 'SELL', ?, ?, ?, ?)
        ''', (user_id, stock_id, quantity, stock['price'], new_balance, realized_pl))
        
        # Record transaction history
        conn.execute('''
            INSERT INTO transaction_history 
            (user_id, stock_id, order_type, quantity, price, total_value, cash_before, cash_after, realized_pl)
            VALUES (?, ?, 'SELL', ?, ?, ?, ?, ?, ?)
        ''', (user_id, stock_id, quantity, stock['price'], total_value, user['balance'], new_balance, realized_pl))
        
        conn.commit()
        
        pl_text = f" (P/L: ${realized_pl:.2f})" if realized_pl != 0 else ""
        flash(f"Successfully sold {quantity} shares of {stock['symbol']} for ${total_value:.2f}{pl_text}", "success")
        
    except Exception as e:
        conn.rollback()
        flash(f"Error selling stock: {str(e)}", "error")
    finally:
        conn.close()
    
    return redirect(url_for('dashboard', user_id=user_id))
    
 # admin panel 
@app.route('/admin')
def admin():
    """Displays a list of users and their balances for management."""
    conn = get_db_connection()
    users = conn.execute('SELECT user_id, username, email, balance FROM users').fetchall()
    conn.close()

    return render_template('admin.html', users=users)


# Admin Routes for User Management
@app.route('/admin/users')
def admin_users():
    """View all users with management options."""
    conn = get_db_connection()
    users = conn.execute('SELECT user_id, username, email, balance FROM users').fetchall()
    conn.close()
    return render_template('admin_users.html', users=users)


@app.route('/admin/user/create', methods=['GET', 'POST'])
def admin_user_create():
    """Create a new user account."""
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
            return redirect(url_for('admin_users'))
        except sqlite3.IntegrityError:
            flash("Username or email already exists.", "error")
        finally:
            conn.close()
    
    return render_template('admin_user_create.html')


# Admin Routes for Stock Management
@app.route('/admin/stocks')
def admin_stocks():
    """View all stocks in the system."""
    conn = get_db_connection()
    stocks = conn.execute('SELECT * FROM stocks').fetchall()
    conn.close()
    return render_template('admin_stocks.html', stocks=stocks)


@app.route('/admin/stock/create', methods=['GET', 'POST'])
def admin_stock_create():
    """Create a new stock."""
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
            return redirect(url_for('admin_stocks'))
        except sqlite3.IntegrityError:
            flash("Stock symbol already exists.", "error")
        finally:
            conn.close()
    
    return render_template('admin_stock_create.html')


@app.route('/admin/stock/update', methods=['GET', 'POST'])
def admin_stock_update():
    """Update stock prices."""
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


# Admin Routes for Market Management
@app.route('/admin/market/hours')
def admin_market_hours():
    """Configure market hours."""
    return render_template('admin_market_hours.html')


@app.route('/admin/market/schedule')
def admin_market_schedule():
    """Set market schedule."""
    return render_template('admin_market_schedule.html')


@app.route('/admin/market/status')
def admin_market_status():
    """Open/close markets."""
    return render_template('admin_market_status.html')


# Admin Routes for System Management
@app.route('/admin/logs')
def admin_logs():
    """View system logs."""
    return render_template('admin_logs.html')


@app.route('/admin/notifications')
def admin_notifications():
    """Manage system notifications."""
    return render_template('admin_notifications.html')


@app.route('/admin/settings')
def admin_settings():
    """Configure system settings."""
    return render_template('admin_settings.html')


# Admin Routes for Analytics & Reports
@app.route('/admin/analytics')
def admin_analytics():
    """View trading analytics."""
    return render_template('admin_analytics.html')


@app.route('/admin/reports')
def admin_reports():
    """Generate system reports."""
    return render_template('admin_reports.html')


@app.route('/admin/export')
def admin_export():
    """Export system data."""
    return render_template('admin_export.html')



# run the flask app
if __name__ == '__main__':
    app.run(debug=True, port=5001)
