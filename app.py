from flask import Flask, render_template, request, redirect, url_for
import sqlite3

app = Flask(__name__)

# Connect helper
def get_db_connection():
    conn = sqlite3.connect('stock_trading.db')
    conn.row_factory = sqlite3.Row
    return conn

# ---------- ROUTES ---------- #

# Home / Login page
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
            return redirect(url_for('dashboard', user_id=user['user_id']))
        else:
            return "Invalid credentials or user not found."
    return render_template('login.html')


# Dashboard (user portfolio + trading)
@app.route('/dashboard/<int:user_id>')
def dashboard(user_id):
    conn = get_db_connection()
    user = conn.execute('SELECT * FROM users WHERE user_id = ?', (user_id,)).fetchone()
    portfolio = conn.execute('''
        SELECT s.symbol, s.company_name, p.quantity, (p.quantity * s.price) AS value
        FROM portfolio p
        JOIN stocks s ON p.stock_id = s.stock_id
        WHERE p.user_id = ?
    ''', (user_id,)).fetchall()
    conn.close()
    return render_template('dashboard.html', user=user, portfolio=portfolio)


# Register new user
@app.route('/register', methods=['POST'])
def register():
    username = request.form['username']
    email = request.form['email']

    conn = get_db_connection()
    try:
        conn.execute('INSERT INTO users (username, email, balance) VALUES (?, ?, ?)',
                     (username, email, 10000.0))  # Start with some demo balance
        conn.commit()
    except sqlite3.IntegrityError:
        return "Username or email already exists."
    finally:
        conn.close()

    return redirect(url_for('login'))


# ---------- Run the server ---------- #
if __name__ == '__main__':
    app.run(debug=True)
