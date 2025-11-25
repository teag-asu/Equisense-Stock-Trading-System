# Simple Stock Trading System Database
# Using SQLite for simplicity

import sqlite3

# Connect to (or create) the database
conn = sqlite3.connect('stock_trading.db')
cursor = conn.cursor()

# Create Users table
cursor.execute('''
ALTER TABLE users ADD COLUMN total_withdrawn REAL DEFAULT 0.0;
''')

# Commit changes and close connection
conn.commit()
conn.close()

