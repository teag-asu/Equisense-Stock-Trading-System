import sqlite3

DB_PATH = "stock_trading.db"

conn = sqlite3.connect(DB_PATH)
conn.row_factory = sqlite3.Row

cur = conn.cursor()

# gets the first user
cur.execute("SELECT user_id, username FROM users ORDER BY user_id ASC LIMIT 1")
user = cur.fetchone()

if not user:
    print("No users found!")
else:
    cur.execute("UPDATE users SET is_admin = 1 WHERE user_id = ?", (user['user_id'],))
    conn.commit()
    print(f"User '{user['username']}' (ID {user['user_id']}) is now an admin.")

conn.close()
