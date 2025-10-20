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

    portfolio = conn.execute('''
        SELECT s.symbol, s.company_name, p.quantity, (p.quantity * s.price) AS value
        FROM portfolio p
        JOIN stocks s ON p.stock_id = s.stock_id
        WHERE p.user_id = ?
    ''', (user_id,)).fetchall()
    conn.close()

    return render_template(
        'dashboard.html',
        user=user,
        balance=user['balance'],
        portfolio=portfolio,
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
    
 # admin panel 
@app.route('/admin')
def admin():
    """Displays a list of users and their balances for management."""
    conn = get_db_connection()
    users = conn.execute('SELECT user_id, username, email, balance FROM users').fetchall()
    conn.close()

    return render_template('admin.html', users=users)



# run the flask app
if __name__ == '__main__':
    app.run(debug=True)
