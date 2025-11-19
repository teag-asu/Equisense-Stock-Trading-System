# Simple Stock Trading System Database
# Using SQLite for simplicity

import sqlite3

# Connect to (or create) the database
conn = sqlite3.connect('stock_trading.db')
cursor = conn.cursor()

# Create Users table
cursor.execute('''
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE,
    email TEXT NOT NULL UNIQUE,
    balance REAL DEFAULT 0.0,
    password_hash TEXT NOT NULL,
    is_admin INTEGER DEFAULT 0
);
''')

# Create Stocks table
cursor.execute('''
CREATE TABLE IF NOT EXISTS stocks (
    stock_id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL UNIQUE,
    company_name TEXT NOT NULL,
    price REAL NOT NULL
);
''')

# Create Orders table (Buy/Sell orders)
cursor.execute('''
CREATE TABLE IF NOT EXISTS orders (
    order_id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    stock_id INTEGER NOT NULL,
    order_type TEXT CHECK(order_type IN ('BUY', 'SELL')) NOT NULL,
    quantity INTEGER NOT NULL,
    price REAL NOT NULL,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
    cash_after REAL DEFAULT 0,
    realized_pl REAL DEFAULT 0,
    FOREIGN KEY (user_id) REFERENCES users(user_id),
    FOREIGN KEY (stock_id) REFERENCES stocks(stock_id)
);
''')

# Create Portfolio table (tracks owned stocks)
cursor.execute('''
CREATE TABLE IF NOT EXISTS portfolio (
    portfolio_id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    stock_id INTEGER NOT NULL,
    quantity INTEGER DEFAULT 0,
    avg_cost REAL DEFAULT 0,
    total_invested REAL DEFAULT 0,
    last_updated TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(user_id),
    FOREIGN KEY (stock_id) REFERENCES stocks(stock_id)
);
''')

# Create transaction history table
cursor.execute('''
CREATE TABLE IF NOT EXISTS transaction_history (
    transaction_id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    stock_id INTEGER NOT NULL,
    order_type TEXT NOT NULL,
    quantity INTEGER NOT NULL,
    price REAL NOT NULL,
    total_value REAL NOT NULL,
    cash_before REAL NOT NULL,
    cash_after REAL NOT NULL,
    realized_pl REAL DEFAULT 0,
    timestamp TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(user_id),
    FOREIGN KEY (stock_id) REFERENCES stocks(stock_id)
);
''')

# Create market schedule table
cursor.execute('''
CREATE TABLE IF NOT EXISTS market_schedule (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    market_open_time TEXT,
    market_close_time TEXT,
    is_open_today INTEGER,
    manual_override INTEGER,
    manual_status TEXT,
    updated_by INTEGER,
    updated_at TEXT
);
''')

# Commit changes and close connection
conn.commit()
conn.close()

print("Stock trading system database created successfully!")
