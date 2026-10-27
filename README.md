# SmartShop

Small business management system for spaza and retail shops
(Flask, SQLite). Records products, stock, sales, daily cash,
expenses and reports.

## Run
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
python create_owner.py
python app.py

## Test
python -m pytest -v

## Backup
python backup.py

## Testing

SmartShop includes automated tests using `pytest`.

To run the tests locally:

```bash
python -m pytest -v
```

**Latest result:** 9 tests passed.
