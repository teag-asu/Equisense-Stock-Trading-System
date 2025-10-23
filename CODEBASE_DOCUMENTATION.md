# EquiSense Stock Trading System — Documentation

## Overview

EquiSense is a Flask + SQLite web application that simulates a basic stock trading platform with user accounts, portfolio tracking, and an administrative panel.

## Architecture & Stack

* **Backend:** Python 3, Flask
* **Templates:** Jinja2 (HTML5)
* **Styles:** CSS (`static/styles.css`)
* **Database:** SQLite (`stock_trading.db`)
* **Default Port:** 5001

## Project Structure

```
EquiSense-Stock-Trading-System/
├── app.py                        # Main Flask app
├── stock_trading.db              # SQLite database
├── static/
│   └── styles.css                # Global styles
├── templates/
│   ├── login.html                # Auth page
│   ├── dashboard.html            # User dashboard
│   ├── admin.html                # Admin hub
│   ├── admin_users.html          # Admin: users list
│   ├── admin_user_create.html    # Admin: create user
│   ├── admin_stocks.html         # Admin: stocks list
│   ├── admin_stock_create.html   # Admin: create stock
│   ├── admin_stock_update.html   # Admin: update prices
│   ├── admin_market_hours.html   # Admin: market hours
│   ├── admin_market_schedule.html# Admin: schedule/holidays
│   ├── admin_logs.html           # Admin: logs
│   ├── admin_settings.html       # Admin: settings
│   ├── admin_analytics.html      # Admin: analytics (placeholder)
│   ├── admin_reports.html        # Admin: reports (placeholder)
│   └── admin_export.html         # Admin: export (placeholder)
├── DB rough draft                # Schema/init notes
└── __pycache__/
```

## Database Schema

Enable foreign keys per connection: `PRAGMA foreign_keys = ON;`

### Table: users

```sql
CREATE TABLE IF NOT EXISTS users (
  user_id   INTEGER PRIMARY KEY AUTOINCREMENT,
  username  TEXT NOT NULL UNIQUE,
  email     TEXT NOT NULL UNIQUE,
  balance   REAL NOT NULL DEFAULT 0.0
);
```

### Table: stocks

```sql
CREATE TABLE IF NOT EXISTS stocks (
  stock_id     INTEGER PRIMARY KEY AUTOINCREMENT,
  symbol       TEXT NOT NULL UNIQUE,
  company_name TEXT NOT NULL,
  price        REAL NOT NULL
);
```

### Table: portfolio

```sql
CREATE TABLE IF NOT EXISTS portfolio (
  portfolio_id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id      INTEGER NOT NULL,
  stock_id     INTEGER NOT NULL,
  quantity     INTEGER NOT NULL DEFAULT 0,
  avg_cost     REAL NOT NULL DEFAULT 0.0,
  UNIQUE(user_id, stock_id),
  FOREIGN KEY(user_id) REFERENCES users(user_id) ON DELETE CASCADE,
  FOREIGN KEY(stock_id) REFERENCES stocks(stock_id) ON DELETE CASCADE
);
```

### Table: orders

```sql
CREATE TABLE IF NOT EXISTS orders (
  order_id   INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id    INTEGER NOT NULL,
  stock_id   INTEGER NOT NULL,
  order_type TEXT NOT NULL CHECK(order_type IN ('BUY','SELL')),
  quantity   INTEGER NOT NULL,
  price      REAL NOT NULL,
  timestamp  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY(user_id) REFERENCES users(user_id) ON DELETE CASCADE,
  FOREIGN KEY(stock_id) REFERENCES stocks(stock_id) ON DELETE CASCADE
);
```

### Table: transaction_history

```sql
CREATE TABLE IF NOT EXISTS transaction_history (
  tx_id       INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id     INTEGER NOT NULL,
  stock_id    INTEGER NOT NULL,
  order_type  TEXT NOT NULL CHECK(order_type IN ('BUY','SELL','DEPOSIT','WITHDRAW')),
  quantity    INTEGER NOT NULL DEFAULT 0,
  price       REAL NOT NULL DEFAULT 0.0,
  total_value REAL NOT NULL DEFAULT 0.0,
  cash_before REAL NOT NULL DEFAULT 0.0,
  cash_after  REAL NOT NULL DEFAULT 0.0,
  realized_pl REAL NOT NULL DEFAULT 0.0,
  timestamp   DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY(user_id) REFERENCES users(user_id) ON DELETE CASCADE,
  FOREIGN KEY(stock_id) REFERENCES stocks(stock_id) ON DELETE CASCADE
);
```

## Security and Sessions

* Parameterized SQL queries for input safety
* Store Flask secret key in an environment variable
* Add passwords with hashing (`werkzeug.security.generate_password_hash`) [pending]
* Implement session-based auth guards (e.g., `@login_required`) [pending]

## Request Flow

1. Authentication: username + email lookup; redirect to dashboard on success
2. Dashboard: fetch user, portfolio, available stocks, recent transactions
3. Trade: validate inputs → update balance → upsert portfolio (qty, avg_cost) → write `orders` and `transaction_history`
4. Admin: CRUD users/stocks; market/settings/logs

## Routes (Index)

### Public/Auth

* `GET /` · `GET /login` — Login page
* `POST /login` — Authenticate
* `POST /register` — Create user with zero balance

### User

* `GET /dashboard/<int:user_id>` — Dashboard
* `POST /deposit/<int:user_id>` — Deposit funds
* `POST /withdraw/<int:user_id>` — Withdraw funds
* `POST /buy_stock/<int:user_id>` — Buy shares
* `POST /sell_stock/<int:user_id>` — Sell shares

### Admin

* `GET /admin` — Admin hub
* `GET /admin/users` — List users
* `GET|POST /admin/user/create` — Create user
* `GET /admin/stocks` — List stocks
* `GET|POST /admin/stock/create` — Create stock
* `GET|POST /admin/stock/update` — Update price
* `GET /admin/market/hours` — Market hours form
* `GET /admin/market/schedule` — Trading days & holidays
* `GET /admin/logs` — View logs
* `GET /admin/settings` — Global settings
* `GET /admin/analytics` — Analytics (placeholder)
* `GET /admin/reports` — Reports (placeholder)
* `GET /admin/export` — Export (placeholder)

## Templates

* `login.html` — Login/registration with flash messages
* `dashboard.html` — Balance, deposit/withdraw, portfolio, trade forms, recent transactions
* `admin.html` — Navigation hub for admin features
* `admin_*` — CRUD/configuration pages with consistent card/panel UI

## Styles

* `static/styles.css` contains panel, form, button, table, flash, and admin link styles plus basic responsive rules

## Installation

### Prerequisites

* Python 3.10+
* `pip install flask`

### Quickstart

```bash
# optional: python -m venv .venv && source .venv/bin/activate
export FLASK_SECRET="your-strong-secret"
python app.py
# open http://localhost:5001
```

### Database Initialization

If using a helper script:

```bash
python "DB rough draft.py"
```

Otherwise, ensure tables are created on app start.

## Trading Logic (Summary)

**Buy**

* Require `qty > 0` and `balance >= qty * price`
* Decrease `users.balance`
* Upsert `portfolio`:

  * `new_qty = old_qty + qty`
  * `new_avg = (old_qty*old_avg + qty*price) / new_qty`
* Insert into `orders` and `transaction_history` (track cash before/after)

**Sell**

* Require `qty > 0` and `qty <= held_qty`
* Increase `users.balance` by `qty * price`
* Realized P/L = `(price - avg_cost) * qty`
* Decrease or remove portfolio row; log `orders` and `transaction_history`

Wrap buy/sell in a transaction and rollback on error.

## Admin Feature Summary

* Users: list, create
* Stocks: list, create, update price
* Market: hours, schedule/holidays
* System: logs, settings
* Analytics/Reports/Export: placeholders for future expansion

## Known Limitations

* No password-based authentication or hashing
* Minimal session management
* No real-time market data
* Buy/Sell are simulated at the stored `stocks.price`
* No role-based access control for admin

## Planned Enhancements

* Password auth with hashing and session guards
* Role-based access control (user/admin)
* Real-time price feeds and historical charts
* Robust transaction handling and audit logs
* API blueprinting and input validation layer
* Improved responsive UI and accessibility

## Conventions

* Use environment variables for secrets/config
* Enforce foreign keys on each SQLite connection
* Group admin features under an `admin` Blueprint (recommended)
