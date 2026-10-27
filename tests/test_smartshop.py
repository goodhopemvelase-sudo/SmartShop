import sqlite3
import pytest
import database


def login(client, username="owner", password="password123"):
    return client.post("/login", data={"username": username, "password": password})


def add_product(client, price="100", cost="60", stock="50"):
    client.post("/products", data={
        "name": "Cola", "selling_price": price, "cost_price": cost,
        "stock_quantity": stock, "reorder_level": "5",
    })


def sell(client, qty, method="cash"):
    return client.post("/sales/new", data={"qty_1": str(qty), "payment_method": method})


def query(sql):
    conn = database.get_connection()
    row = conn.execute(sql).fetchone()
    conn.close()
    return row


def test_wrong_password_is_rejected(client):
    response = login(client, password="wrong")
    assert b"Wrong username or password" in response.data


def test_pages_need_login(client):
    response = client.get("/products")
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/login")


def test_sale_reduces_stock(client):
    login(client)
    add_product(client)
    sell(client, 20)
    assert query("SELECT stock_quantity FROM products WHERE id = 1")[0] == 30


def test_cannot_sell_more_than_stock(client):
    login(client)
    add_product(client)
    sell(client, 999)
    assert query("SELECT stock_quantity FROM products WHERE id = 1")[0] == 50
    assert query("SELECT COUNT(*) FROM sales")[0] == 0


def test_cancel_sale_returns_stock(client):
    login(client)
    add_product(client)
    sell(client, 20)
    client.post("/sales/1/cancel")
    assert query("SELECT stock_quantity FROM products WHERE id = 1")[0] == 50
    assert query("SELECT status FROM sales WHERE id = 1")[0] == "cancelled"


def test_cash_reconciliation_example_from_document(client):
    login(client)
    add_product(client)
    client.post("/cash/open", data={"opening_cash": "500"})
    sell(client, 20)  # R2,000 cash sales
    client.post("/cash/transaction", data={"type": "cash_in", "amount": "100", "description": "Top up"})
    client.post("/expenses", data={
        "expense_date": "2026-10-27", "category": "Transport",
        "description": "Taxi", "amount": "250", "payment_method": "cash",
    })
    client.post("/cash/transaction", data={"type": "withdrawal", "amount": "300", "description": "Owner"})
    client.post("/cash/close", data={"actual_closing": "2030"})

    expected, difference = query("SELECT expected_closing, difference FROM cash_sessions WHERE id = 1")
    assert expected == 2050
    assert difference == -20


def test_card_sale_does_not_enter_the_till(client):
    login(client)
    add_product(client)
    client.post("/cash/open", data={"opening_cash": "500"})
    sell(client, 5, method="card")
    client.post("/cash/close", data={"actual_closing": "500"})
    expected, difference = query("SELECT expected_closing, difference FROM cash_sessions WHERE id = 1")
    assert expected == 500
    assert difference == 0


def test_cashier_cannot_open_reports(client):
    login(client, "cashier")
    assert client.get("/reports").status_code == 403


def test_database_rejects_negative_price():
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE p (price REAL CHECK (price >= 0))")
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO p VALUES (-5)")