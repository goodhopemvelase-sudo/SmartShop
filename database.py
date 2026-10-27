import sqlite3
DB_PATH = "smartshop.db"


def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def create_tables():
    conn = get_connection()

    conn.execute("""
        CREATE TABLE IF NOT EXISTS products (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            name           TEXT NOT NULL,
            selling_price  REAL NOT NULL CHECK (selling_price >= 0),
            cost_price     REAL NOT NULL CHECK (cost_price >= 0),
            stock_quantity INTEGER NOT NULL DEFAULT 0 CHECK (stock_quantity >= 0),
            reorder_level  INTEGER NOT NULL DEFAULT 0,
            is_active      INTEGER NOT NULL DEFAULT 1
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS stock_movements (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            product_id    INTEGER NOT NULL,
            movement_type TEXT NOT NULL,
            quantity      INTEGER NOT NULL,
            reason        TEXT NOT NULL,
            created_at    TEXT NOT NULL DEFAULT (datetime('now')),
            FOREIGN KEY (product_id) REFERENCES products(id)
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            username      TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            role          TEXT NOT NULL DEFAULT 'owner',
            is_active     INTEGER NOT NULL DEFAULT 1,
            created_at    TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """
)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS sales (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id        INTEGER,
            payment_method TEXT NOT NULL,
            status         TEXT NOT NULL DEFAULT 'completed',
            total_amount   REAL NOT NULL CHECK (total_amount >= 0),
            created_at     TEXT NOT NULL DEFAULT (datetime('now')),
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS sale_items (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            sale_id    INTEGER NOT NULL,
            product_id INTEGER NOT NULL,
            quantity   INTEGER NOT NULL CHECK (quantity > 0),
            unit_price REAL NOT NULL CHECK (unit_price >= 0),
            unit_cost  REAL NOT NULL CHECK (unit_cost >= 0),
            FOREIGN KEY (sale_id) REFERENCES sales(id),
            FOREIGN KEY (product_id) REFERENCES products(id)
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS cash_sessions (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id          INTEGER,
            session_date     TEXT NOT NULL,
            opening_cash     REAL NOT NULL CHECK (opening_cash >= 0),
            expected_closing REAL,
            actual_closing   REAL,
            difference       REAL,
            status           TEXT NOT NULL DEFAULT 'open',
            opened_at        TEXT NOT NULL DEFAULT (datetime('now')),
            closed_at        TEXT,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS cash_transactions (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id  INTEGER NOT NULL,
            type        TEXT NOT NULL,
            amount      REAL NOT NULL CHECK (amount > 0),
            description TEXT NOT NULL,
            created_at  TEXT NOT NULL DEFAULT (datetime('now')),
            FOREIGN KEY (session_id) REFERENCES cash_sessions(id)
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS expenses (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            expense_date   TEXT NOT NULL,
            category       TEXT NOT NULL,
            description    TEXT NOT NULL,
            amount         REAL NOT NULL CHECK (amount > 0),
            payment_method TEXT NOT NULL,
            user_id        INTEGER,
            created_at     TEXT NOT NULL DEFAULT (datetime('now')),
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS audit_logs (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id    INTEGER,
            action     TEXT NOT NULL,
            table_name TEXT NOT NULL,
            record_id  INTEGER,
            details    TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    """)
    conn.commit()
    conn.close()


if __name__ == "__main__":
    create_tables()
    print("Database ready.")