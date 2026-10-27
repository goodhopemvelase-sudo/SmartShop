import os
import sqlite3
from datetime import date
from functools import wraps
from flask import Flask, render_template, request, redirect, session
from werkzeug.security import check_password_hash, generate_password_hash
from database import get_connection, create_tables

app = Flask(__name__)
app.secret_key = os.environ.get("SMARTSHOP_SECRET", "dev-only-change-me")
create_tables()

EXPENSE_CATEGORIES = [
    "Stock purchases", "Transport", "Electricity", "Rent",
    "Airtime and data", "Repairs", "Supplies", "Other",
]


def login_required(view):
    @wraps(view)
    def wrapped_view(*args, **kwargs):
        if "user_id" not in session:
            return redirect("/login")
        return view(*args, **kwargs)
    return wrapped_view


def write_audit(conn, action, table_name, record_id, details):
    conn.execute(
        """INSERT INTO audit_logs (user_id, action, table_name, record_id, details)
           VALUES (?, ?, ?, ?, ?)""",
        (session.get("user_id"), action, table_name, record_id, details),
    )

USER_ROLES = ["owner", "cashier", "stock_controller"]

PUBLIC_ENDPOINTS = {"home", "login", "logout", "static"}

ROLE_ACCESS = {
    "cashier": {
        "new_sale", "sales_list", "cash", "open_cash_session",
        "add_cash_transaction", "close_cash_session", "cash_session_result",
    },
    "stock_controller": {
        "products", "edit_product", "stock_in", "stock_history",
    },
}


@app.before_request
def check_access():
    endpoint = request.endpoint

    if endpoint is None or endpoint in PUBLIC_ENDPOINTS:
        return None

    if "user_id" not in session or "role" not in session:
        return redirect("/login")

    role = session["role"]

    if role == "owner":
        return None

    if endpoint in ROLE_ACCESS.get(role, set()):
        return None

    return render_template("forbidden.html"), 403

@app.route("/")
def home():
    return render_template("home.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    error = None

    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]

        conn = get_connection()
        user = conn.execute(
            "SELECT * FROM users WHERE username = ? AND is_active = 1",
            (username,),
        ).fetchone()
        conn.close()

        if user and check_password_hash(user["password_hash"], password):
            session.clear()
            session["user_id"] = user["id"]
            session["username"] = user["username"]
            session["role"] = user["role"]
            return redirect("/")

        error = "Wrong username or password."

    return render_template("login.html", error=error)


@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return redirect("/login")


@app.route("/products", methods=["GET", "POST"])
@login_required
def products():
    conn = get_connection()

    if request.method == "POST":
        conn.execute(
            """INSERT INTO products
               (name, selling_price, cost_price, stock_quantity, reorder_level)
               VALUES (?, ?, ?, ?, ?)""",
            (
                request.form["name"],
                request.form["selling_price"],
                request.form["cost_price"],
                request.form["stock_quantity"],
                request.form["reorder_level"],
            ),
        )
        conn.commit()
        conn.close()
        return redirect("/products")

    all_products = conn.execute("SELECT * FROM products WHERE is_active = 1").fetchall()
    conn.close()
    return render_template("products.html", products=all_products)


@app.route("/products/<int:product_id>/deactivate", methods=["POST"])
@login_required
def deactivate_product(product_id):
    conn = get_connection()
    conn.execute("UPDATE products SET is_active = 0 WHERE id = ?", (product_id,))
    write_audit(conn, "product_deactivated", "products", product_id, "Product deactivated")
    conn.commit()
    conn.close()
    return redirect("/products")


@app.route("/products/<int:product_id>/edit", methods=["GET", "POST"])
@login_required
def edit_product(product_id):
    conn = get_connection()

    if request.method == "POST":
        conn.execute(
            """UPDATE products
               SET name = ?, selling_price = ?, cost_price = ?, reorder_level = ?
               WHERE id = ?""",
            (
                request.form["name"],
                request.form["selling_price"],
                request.form["cost_price"],
                request.form["reorder_level"],
                product_id,
            ),
        )
        conn.commit()
        conn.close()
        return redirect("/products")

    product = conn.execute("SELECT * FROM products WHERE id = ?", (product_id,)).fetchone()
    conn.close()
    return render_template("edit_product.html", product=product)


@app.route("/products/<int:product_id>/stock-in", methods=["GET", "POST"])
@login_required
def stock_in(product_id):
    conn = get_connection()

    if request.method == "POST":
        quantity = int(request.form["quantity"])
        reason = request.form["reason"]

        conn.execute(
            """INSERT INTO stock_movements (product_id, movement_type, quantity, reason)
               VALUES (?, 'received', ?, ?)""",
            (product_id, quantity, reason),
        )
        conn.execute(
            "UPDATE products SET stock_quantity = stock_quantity + ? WHERE id = ?",
            (quantity, product_id),
        )
        conn.commit()
        conn.close()
        return redirect("/products")

    product = conn.execute("SELECT * FROM products WHERE id = ?", (product_id,)).fetchone()
    conn.close()
    return render_template("stock_in.html", product=product)


@app.route("/stock-history")
@login_required
def stock_history():
    conn = get_connection()
    movements = conn.execute(
        """SELECT stock_movements.created_at,
                  products.name AS product_name,
                  stock_movements.movement_type,
                  stock_movements.quantity,
                  stock_movements.reason
           FROM stock_movements
           JOIN products ON products.id = stock_movements.product_id
           ORDER BY stock_movements.id DESC"""
    ).fetchall()
    conn.close()
    return render_template("stock_history.html", movements=movements)


@app.route("/sales/new", methods=["GET", "POST"])
@login_required
def new_sale():
    conn = get_connection()
    all_products = conn.execute(
        "SELECT * FROM products WHERE is_active = 1 AND stock_quantity > 0"
    ).fetchall()
    error = None

    if request.method == "POST":
        payment_method = request.form["payment_method"]
        items = []
        total = 0

        for p in all_products:
            qty_text = request.form.get("qty_" + str(p["id"]), "0")
            qty = int(qty_text) if qty_text.isdigit() else 0

            if qty > 0:
                if qty > p["stock_quantity"]:
                    error = "Not enough stock for " + p["name"] + " (only " + str(p["stock_quantity"]) + " left)."
                    break
                items.append((p, qty))
                total += qty * p["selling_price"]

        if error is None and not items:
            error = "Choose at least one product."

        if error is None:
            cursor = conn.execute(
                """INSERT INTO sales (user_id, payment_method, status, total_amount)
                   VALUES (?, ?, 'completed', ?)""",
                (session["user_id"], payment_method, round(total, 2)),
            )
            sale_id = cursor.lastrowid

            for p, qty in items:
                conn.execute(
                    """INSERT INTO sale_items (sale_id, product_id, quantity, unit_price, unit_cost)
                       VALUES (?, ?, ?, ?, ?)""",
                    (sale_id, p["id"], qty, p["selling_price"], p["cost_price"]),
                )
                conn.execute(
                    "UPDATE products SET stock_quantity = stock_quantity - ? WHERE id = ?",
                    (qty, p["id"]),
                )
                conn.execute(
                    """INSERT INTO stock_movements (product_id, movement_type, quantity, reason)
                       VALUES (?, 'sold', ?, ?)""",
                    (p["id"], -qty, "Sale #" + str(sale_id)),
                )

            write_audit(conn, "sale_completed", "sales", sale_id, "Total R" + str(round(total, 2)) + " paid by " + payment_method)
            conn.commit()
            conn.close()
            return redirect("/products")

    conn.close()
    return render_template("new_sale.html", products=all_products, error=error)


@app.route("/sales")
@login_required
def sales_list():
    conn = get_connection()
    sales = conn.execute(
        """SELECT sales.id, sales.created_at, sales.payment_method,
                  sales.status, sales.total_amount, users.username
           FROM sales
           LEFT JOIN users ON users.id = sales.user_id
           ORDER BY sales.id DESC"""
    ).fetchall()
    total_sales = conn.execute(
        "SELECT COALESCE(SUM(total_amount), 0) FROM sales WHERE status = 'completed'"
    ).fetchone()[0]
    conn.close()
    return render_template("sales.html", sales=sales, total_sales=total_sales)


@app.route("/sales/<int:sale_id>/cancel", methods=["POST"])
@login_required
def cancel_sale(sale_id):
    conn = get_connection()

    sale = conn.execute(
        "SELECT * FROM sales WHERE id = ? AND status = 'completed'",
        (sale_id,),
    ).fetchone()

    if sale is None:
        conn.close()
        return redirect("/sales")

    items = conn.execute(
        "SELECT product_id, quantity FROM sale_items WHERE sale_id = ?",
        (sale_id,),
    ).fetchall()

    conn.execute("UPDATE sales SET status = 'cancelled' WHERE id = ?", (sale_id,))

    for item in items:
        conn.execute(
            "UPDATE products SET stock_quantity = stock_quantity + ? WHERE id = ?",
            (item["quantity"], item["product_id"]),
        )
        conn.execute(
            """INSERT INTO stock_movements (product_id, movement_type, quantity, reason)
               VALUES (?, 'returned', ?, ?)""",
            (item["product_id"], item["quantity"], "Sale #" + str(sale_id) + " cancelled"),
        )

    write_audit(conn, "sale_cancelled", "sales", sale_id, "Sale cancelled and stock returned")
    conn.commit()
    conn.close()
    return redirect("/sales")


@app.route("/cash")
@login_required
def cash():
    error = request.args.get("error")
    conn = get_connection()
    cash_session = conn.execute(
        "SELECT * FROM cash_sessions WHERE status = 'open' ORDER BY id DESC LIMIT 1"
    ).fetchone()

    cash_sales = 0
    cash_in = 0
    cash_expenses = 0
    withdrawals = 0
    expected = None
    transactions = []

    if cash_session:
        cash_sales = conn.execute(
            """SELECT COALESCE(SUM(total_amount), 0) FROM sales
               WHERE payment_method = 'cash'
                 AND status = 'completed'
                 AND created_at >= ?""",
            (cash_session["opened_at"],),
        ).fetchone()[0]

        rows = conn.execute(
            """SELECT type, COALESCE(SUM(amount), 0) AS total
               FROM cash_transactions
               WHERE session_id = ?
               GROUP BY type""",
            (cash_session["id"],),
        ).fetchall()
        for row in rows:
            if row["type"] == "cash_in":
                cash_in = row["total"]
            elif row["type"] == "expense":
                cash_expenses = row["total"]
            elif row["type"] == "withdrawal":
                withdrawals = row["total"]

        expected = (
            cash_session["opening_cash"] + cash_sales + cash_in
            - cash_expenses - withdrawals
        )

        transactions = conn.execute(
            "SELECT * FROM cash_transactions WHERE session_id = ? ORDER BY id DESC",
            (cash_session["id"],),
        ).fetchall()

    conn.close()
    return render_template(
        "cash.html",
        cash_session=cash_session,
        cash_sales=cash_sales,
        cash_in=cash_in,
        cash_expenses=cash_expenses,
        withdrawals=withdrawals,
        expected=expected,
        transactions=transactions,
        error=error,
    )


@app.route("/cash/open", methods=["POST"])
@login_required
def open_cash_session():
    conn = get_connection()

    already_open = conn.execute(
        "SELECT id FROM cash_sessions WHERE status = 'open'"
    ).fetchone()

    if already_open is None:
        opening_cash = float(request.form["opening_cash"])
        if opening_cash >= 0:
            conn.execute(
                """INSERT INTO cash_sessions (user_id, session_date, opening_cash)
                   VALUES (?, date('now'), ?)""",
                (session["user_id"], opening_cash),
            )
            conn.commit()

    conn.close()
    return redirect("/cash")


@app.route("/cash/transaction", methods=["POST"])
@login_required
def add_cash_transaction():
    conn = get_connection()

    cash_session = conn.execute(
        "SELECT id FROM cash_sessions WHERE status = 'open' ORDER BY id DESC LIMIT 1"
    ).fetchone()

    if cash_session is None:
        conn.close()
        return redirect("/cash")

    movement_type = request.form["type"]
    description = request.form["description"].strip()

    try:
        amount = float(request.form["amount"])
    except ValueError:
        amount = 0

    if movement_type not in ("cash_in", "withdrawal"):
        conn.close()
        return redirect("/cash?error=Invalid movement type.")

    if amount <= 0 or description == "":
        conn.close()
        return redirect("/cash?error=Enter an amount above zero and a description.")

    conn.execute(
        """INSERT INTO cash_transactions (session_id, type, amount, description)
           VALUES (?, ?, ?, ?)""",
        (cash_session["id"], movement_type, round(amount, 2), description),
    )
    conn.commit()
    conn.close()
    return redirect("/cash")


@app.route("/cash/close", methods=["POST"])
@login_required
def close_cash_session():
    conn = get_connection()

    cash_session = conn.execute(
        "SELECT * FROM cash_sessions WHERE status = 'open' ORDER BY id DESC LIMIT 1"
    ).fetchone()

    if cash_session is None:
        conn.close()
        return redirect("/cash")

    try:
        actual = float(request.form["actual_closing"])
    except ValueError:
        actual = -1

    if actual < 0:
        conn.close()
        return redirect("/cash?error=Enter the cash counted (zero or more).")

    cash_sales = conn.execute(
        """SELECT COALESCE(SUM(total_amount), 0) FROM sales
           WHERE payment_method = 'cash'
             AND status = 'completed'
             AND created_at >= ?""",
        (cash_session["opened_at"],),
    ).fetchone()[0]

    totals = {"cash_in": 0, "expense": 0, "withdrawal": 0}
    rows = conn.execute(
        """SELECT type, COALESCE(SUM(amount), 0) AS total
           FROM cash_transactions
           WHERE session_id = ?
           GROUP BY type""",
        (cash_session["id"],),
    ).fetchall()
    for row in rows:
        totals[row["type"]] = row["total"]

    expected = round(
        cash_session["opening_cash"] + cash_sales + totals["cash_in"]
        - totals["expense"] - totals["withdrawal"],
        2,
    )
    difference = round(actual - expected, 2)

    conn.execute(
        """UPDATE cash_sessions
           SET expected_closing = ?, actual_closing = ?, difference = ?,
               status = 'closed', closed_at = datetime('now')
           WHERE id = ?""",
        (expected, round(actual, 2), difference, cash_session["id"]),
    )
    write_audit(conn, "till_closed", "cash_sessions", cash_session["id"], "Expected R" + str(expected) + ", counted R" + str(round(actual, 2)) + ", difference R" + str(difference))
    conn.commit()
    conn.close()
    return redirect("/cash/session/" + str(cash_session["id"]))


@app.route("/cash/session/<int:session_id>")
@login_required
def cash_session_result(session_id):
    conn = get_connection()
    cash_session = conn.execute(
        "SELECT * FROM cash_sessions WHERE id = ? AND status = 'closed'",
        (session_id,),
    ).fetchone()
    conn.close()

    if cash_session is None:
        return redirect("/cash")

    return render_template("cash_closed.html", cash_session=cash_session)


@app.route("/cash/history")
@login_required
def cash_history():
    conn = get_connection()
    sessions = conn.execute(
        """SELECT cash_sessions.*, users.username
           FROM cash_sessions
           LEFT JOIN users ON users.id = cash_sessions.user_id
           WHERE cash_sessions.status = 'closed'
           ORDER BY cash_sessions.id DESC"""
    ).fetchall()
    total_difference = conn.execute(
        "SELECT COALESCE(SUM(difference), 0) FROM cash_sessions WHERE status = 'closed'"
    ).fetchone()[0]
    conn.close()
    return render_template(
        "cash_history.html",
        sessions=sessions,
        total_difference=total_difference,
    )


@app.route("/expenses", methods=["GET", "POST"])
@login_required
def expenses():
    conn = get_connection()
    error = None

    if request.method == "POST":
        expense_date = request.form["expense_date"]
        category = request.form["category"]
        description = request.form["description"].strip()
        payment_method = request.form["payment_method"]

        try:
            amount = float(request.form["amount"])
        except ValueError:
            amount = 0

        open_till = conn.execute(
            "SELECT id FROM cash_sessions WHERE status = 'open' ORDER BY id DESC LIMIT 1"
        ).fetchone()

        if amount <= 0 or description == "" or expense_date == "":
            error = "Enter a date, a description and an amount above zero."
        elif category not in EXPENSE_CATEGORIES:
            error = "Choose a valid category."
        elif payment_method not in ("cash", "card", "bank_transfer"):
            error = "Choose a valid payment method."
        elif payment_method == "cash" and open_till is None:
            error = "Open the till first. A cash expense must come out of an open till."

        if error is None:
            amount = round(amount, 2)
            conn.execute(
                """INSERT INTO expenses
                   (expense_date, category, description, amount, payment_method, user_id)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (expense_date, category, description, amount, payment_method, session["user_id"]),
            )
            if payment_method == "cash":
                conn.execute(
                    """INSERT INTO cash_transactions (session_id, type, amount, description)
                       VALUES (?, 'expense', ?, ?)""",
                    (open_till["id"], amount, category + ": " + description),
                )
            conn.commit()
            conn.close()
            return redirect("/expenses")

    start = request.args.get("start", "")
    end = request.args.get("end", "")
    category_filter = request.args.get("category_filter", "")

    sql = """SELECT expenses.*, users.username
             FROM expenses
             LEFT JOIN users ON users.id = expenses.user_id
             WHERE 1 = 1"""
    params = []
    if start:
        sql += " AND expenses.expense_date >= ?"
        params.append(start)
    if end:
        sql += " AND expenses.expense_date <= ?"
        params.append(end)
    if category_filter:
        sql += " AND expenses.category = ?"
        params.append(category_filter)
    sql += " ORDER BY expenses.expense_date DESC, expenses.id DESC"

    rows = conn.execute(sql, params).fetchall()
    conn.close()

    total = sum(r["amount"] for r in rows)

    return render_template(
        "expenses.html",
        expenses=rows,
        total=total,
        categories=EXPENSE_CATEGORIES,
        today=date.today().isoformat(),
        start=start,
        end=end,
        category_filter=category_filter,
        error=error,
    )


@app.route("/reports")
@login_required
def reports():
    today_date = date.today()
    today = today_date.isoformat()
    month_start = today_date.replace(day=1).isoformat()
    error = None

    try:
        start = date.fromisoformat(request.args.get("start", today)).isoformat()
        end = date.fromisoformat(request.args.get("end", today)).isoformat()
    except ValueError:
        start = today
        end = today
        error = "Invalid date. Showing today."

    if start > end:
        start, end = end, start
        error = "The start date was after the end date, so they were swapped."

    conn = get_connection()

    summary = conn.execute(
        """SELECT COUNT(*) AS sales_count,
                  COALESCE(SUM(total_amount), 0) AS revenue
           FROM sales
           WHERE status = 'completed'
             AND date(created_at, 'localtime') BETWEEN ? AND ?""",
        (start, end),
    ).fetchone()

    cogs = conn.execute(
        """SELECT COALESCE(SUM(sale_items.quantity * sale_items.unit_cost), 0)
           FROM sale_items
           JOIN sales ON sales.id = sale_items.sale_id
           WHERE sales.status = 'completed'
             AND date(sales.created_at, 'localtime') BETWEEN ? AND ?""",
        (start, end),
    ).fetchone()[0]

    by_method = conn.execute(
        """SELECT payment_method,
                  COUNT(*) AS count,
                  SUM(total_amount) AS total
           FROM sales
           WHERE status = 'completed'
             AND date(created_at, 'localtime') BETWEEN ? AND ?
           GROUP BY payment_method
           ORDER BY total DESC""",
        (start, end),
    ).fetchall()

    top_products = conn.execute(
        """SELECT products.name,
                  SUM(sale_items.quantity) AS units,
                  SUM(sale_items.quantity * sale_items.unit_price) AS revenue
           FROM sale_items
           JOIN sales ON sales.id = sale_items.sale_id
           JOIN products ON products.id = sale_items.product_id
           WHERE sales.status = 'completed'
             AND date(sales.created_at, 'localtime') BETWEEN ? AND ?
           GROUP BY products.id
           ORDER BY units DESC
           LIMIT 5""",
        (start, end),
    ).fetchall()

    expenses_by_category = conn.execute(
        """SELECT category, SUM(amount) AS total
           FROM expenses
           WHERE expense_date BETWEEN ? AND ?
           GROUP BY category
           ORDER BY total DESC""",
        (start, end),
    ).fetchall()
    expenses_total = sum(e["total"] for e in expenses_by_category)

    closed_sessions = conn.execute(
        """SELECT * FROM cash_sessions
           WHERE status = 'closed'
             AND session_date BETWEEN ? AND ?
           ORDER BY id DESC""",
        (start, end),
    ).fetchall()
    difference_total = sum(s["difference"] for s in closed_sessions)

    low_stock = conn.execute(
        """SELECT name, stock_quantity, reorder_level
           FROM products
           WHERE is_active = 1 AND stock_quantity <= reorder_level
           ORDER BY name"""
    ).fetchall()

    conn.close()

    return render_template(
        "reports.html",
        start=start,
        end=end,
        today=today,
        month_start=month_start,
        error=error,
        sales_count=summary["sales_count"],
        revenue=summary["revenue"],
        cogs=cogs,
        gross_profit=round(summary["revenue"] - cogs, 2),
        by_method=by_method,
        top_products=top_products,
        expenses_by_category=expenses_by_category,
        expenses_total=expenses_total,
        closed_sessions=closed_sessions,
        difference_total=difference_total,
        low_stock=low_stock,
    )


@app.route("/audit-log")
@login_required
def audit_log():
    conn = get_connection()
    logs = conn.execute(
        """SELECT audit_logs.*, users.username
           FROM audit_logs
           LEFT JOIN users ON users.id = audit_logs.user_id
           ORDER BY audit_logs.id DESC
           LIMIT 200"""
    ).fetchall()
    conn.close()
    return render_template("audit_log.html", logs=logs)
@app.route("/users", methods=["GET", "POST"])
def users():
    conn = get_connection()
    error = None

    if request.method == "POST":
        username = request.form["username"].strip()
        password = request.form["password"]
        role = request.form["role"]

        if username == "" or len(password) < 8:
            error = "Enter a username and a password of at least 8 characters."
        elif role not in USER_ROLES:
            error = "Choose a valid role."
        else:
            try:
                cursor = conn.execute(
                    "INSERT INTO users (username, password_hash, role) VALUES (?, ?, ?)",
                    (username, generate_password_hash(password), role),
                )
                write_audit(conn, "user_created", "users", cursor.lastrowid, "Role: " + role)
                conn.commit()
                conn.close()
                return redirect("/users")
            except sqlite3.IntegrityError:
                error = "That username is already taken."

    all_users = conn.execute(
        "SELECT id, username, role, is_active, created_at FROM users ORDER BY id"
    ).fetchall()
    conn.close()
    return render_template("users.html", users=all_users, roles=USER_ROLES, error=error)


@app.route("/users/<int:user_id>/deactivate", methods=["POST"])
def deactivate_user(user_id):
    if user_id != session["user_id"]:
        conn = get_connection()
        conn.execute("UPDATE users SET is_active = 0 WHERE id = ?", (user_id,))
        write_audit(conn, "user_deactivated", "users", user_id, "User deactivated")
        conn.commit()
        conn.close()
    return redirect("/users")

if __name__ == "__main__":
    app.run(debug=True)