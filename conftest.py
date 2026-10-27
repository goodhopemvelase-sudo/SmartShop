import pytest
from werkzeug.security import generate_password_hash
import database


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DB_PATH", str(tmp_path / "test.db"))
    database.create_tables()

    conn = database.get_connection()
    for username, role in (("owner", "owner"), ("cashier", "cashier")):
        conn.execute(
            "INSERT INTO users (username, password_hash, role) VALUES (?, ?, ?)",
            (username, generate_password_hash("password123"), role),
        )
    conn.commit()
    conn.close()

    import app as app_module
    app_module.app.config["TESTING"] = True
    return app_module.app.test_client()