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


# home / login page
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
 
# logout function
@app.route('/logout', methods=['POST'])
def logout():
    # to be implemented later, since the app doesn't use sessions yet; I just wanted to put in the UI element now
    flash("You have been logged out.", "success")
    return redirect(url_for('login'))


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

    # get user's holdings
    holdings = conn.execute('''
        SELECT s.symbol, p.quantity AS shares, (p.quantity * s.price) AS value
        FROM portfolio p
        JOIN stocks s ON p.stock_id = s.stock_id
        WHERE p.user_id = ?
    ''', (user_id,)).fetchall()

    # get full stock list
    stock_list = conn.execute('SELECT symbol, company_name AS name, price FROM stocks').fetchall()
    conn.close()

    return render_template(
        'dashboard.html',
        user=user,
        balance=user['balance'],
        holdings=holdings,
        stock_list=stock_list,
        user_id=user_id
)




# unified deposit/withdraw
@app.route('/depositwithdraw/<int:user_id>', methods=['POST'])
def depositwithdraw(user_id):
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
        flash(f"Deposited ${amount:.2f}.", "success")
    elif action == 'withdraw':
        if balance < amount:
            flash("Insufficient funds.", "error")
            conn.close()
            return redirect(url_for('dashboard', user_id=user_id))
        conn.execute('UPDATE users SET balance = balance - ? WHERE user_id = ?', (amount, user_id))
        flash(f"Withdrew ${amount:.2f}.", "success")

    conn.commit()
    conn.close()
    return redirect(url_for('dashboard', user_id=user_id))


# unified buy/sell stock
@app.route('/trade/<int:user_id>', methods=['POST'])
def trade(user_id):
    action = request.form['action']
    symbol = request.form['symbol'].upper()
    shares = int(request.form['shares'])

    conn = get_db_connection()
    stock = conn.execute('SELECT * FROM stocks WHERE symbol = ?', (symbol,)).fetchone()

    if not stock:
        conn.close()
        flash("Stock not found.", "error")
        return redirect(url_for('dashboard', user_id=user_id))

    stock_id = stock['stock_id']
    price = stock['price']  
    total_cost = shares * price

    user = conn.execute('SELECT balance FROM users WHERE user_id = ?', (user_id,)).fetchone()

    if not user:
        conn.close()
        flash("User not found.", "error")
        return redirect(url_for('login'))

    if action == 'buy':
        if user['balance'] < total_cost:
            conn.close()
            flash("Insufficient funds to buy this stock.", "error")
            return redirect(url_for('dashboard', user_id=user_id))

        # subtract balance, add shares to portfolio
        conn.execute('UPDATE users SET balance = balance - ? WHERE user_id = ?', (total_cost, user_id))
        conn.execute('''
            INSERT INTO portfolio (user_id, stock_id, quantity)
            VALUES (?, ?, ?)
            ON CONFLICT(user_id, stock_id) DO UPDATE SET quantity = quantity + excluded.quantity
        ''', (user_id, stock_id, shares))
        flash(f"Successfully bought {shares} shares of {symbol}.", "success")

    elif action == 'sell':
        holding = conn.execute(
            'SELECT quantity FROM portfolio WHERE user_id = ? AND stock_id = ?',
            (user_id, stock_id)
        ).fetchone()

        if not holding or holding['quantity'] < shares:
            conn.close()
            flash("Not enough shares to sell.", "error")
            return redirect(url_for('dashboard', user_id=user_id))

        # add balance, remove shares
        conn.execute('UPDATE users SET balance = balance + ? WHERE user_id = ?', (total_cost, user_id))
        conn.execute('UPDATE portfolio SET quantity = quantity - ? WHERE user_id = ? AND stock_id = ?',
                     (shares, user_id, stock_id))
        # remove the holding from portfolio if quantity hits zero
        conn.execute('DELETE FROM portfolio WHERE user_id = ? AND stock_id = ? AND quantity <= 0',
             (user_id, stock_id))
        flash(f"Successfully sold {shares} shares of {symbol}.", "success")

    conn.commit()
    conn.close()
    return redirect(url_for('dashboard', user_id=user_id))



    
 # admin panel 
@app.route('/admin')
def admin():
    conn = get_db_connection()
    users = conn.execute('SELECT user_id, username, email, balance FROM users').fetchall()
    conn.close()

    return render_template('admin.html', users=users)
    
# create stock function
@app.route('/create_stock', methods=['POST'])
def create_stock():
    symbol = request.form['symbol'].upper().strip()
    company_name = request.form['company_name'].strip()
    total_volume = int(request.form['total_volume'])
    price = float(request.form['price'])

    conn = get_db_connection()

    # checks if ticker already exists
    existing = conn.execute('SELECT * FROM stocks WHERE symbol = ?', (symbol,)).fetchone()
    if existing:
        conn.close()
        flash(f"Stock with ticker '{symbol}' already exists.", "error")
        return redirect(url_for('admin'))

    # inserts new stock
    conn.execute(
        'INSERT INTO stocks (symbol, company_name, price) VALUES (?, ?, ?)',
        (symbol, company_name, price)
    )
    conn.commit()
    conn.close()

    flash(f"New stock '{company_name}' ({symbol}) created successfully at ${price:.2f}.", "success")
    return redirect(url_for('admin'))




# run the flask app
if __name__ == '__main__':
    app.run(debug=True)
