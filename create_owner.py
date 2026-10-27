from werkzeug.security import generate_password_hash
from database import get_connection,create_tables

create_tables()

username = input("Choose a username: ")
password = input("Choose a password: ")

conn = get_connection()
conn.execute(
    "INSERT INTO users (username, password_hash, role) VALUES (?, ?, 'owner')",
    (username, generate_password_hash(password)),
)
conn.commit()
conn.close()

print("Owner account created.")