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
    balance REAL DEFAULT 0.0
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
    FOREIGN KEY (user_id) REFERENCES users(user_id),
    FOREIGN KEY (stock_id) REFERENCES stocks(stock_id)
);
''')

# Create Portfolio table (tracks owned stocks)
cursor.execute('''
CREATE TABLE IF NOT EXISTS portfolio(
    PORTFOLIO_ID INTEGER PRIMARY KEY AUTOINCREMENT,
    USER_ID INTEGER NOT NULL,
    STOCK_ID INTEGER NOT NULL,
    QUANTITY INTEGER NOT NULL CHECK (QUANTITY >= 0),
    UNIQUE(USER_ID, STOCK_ID),
    FOREIGN KEY (USER_ID) REFERENCES USERS(USER_ID),
    FOREIGN KEY (STOCK_ID) REFERENCES STOCKS(STOCK_ID)
);

''')

# Commit changes and close connection
conn.commit()
conn.close()

print("Stock trading system database created successfully!")
