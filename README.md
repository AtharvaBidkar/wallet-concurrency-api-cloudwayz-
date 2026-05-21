# High-Velocity Wallet REST API

A production-ready, asynchronous FastAPI wallet system designed to handle high-velocity concurrent writes to a single record without data loss or corruption. Built with FastAPI, PostgreSQL, SQLAlchemy 2.0 (Async), and Docker.

## Concurrency Strategy: Atomic SQL Updates

Standard application-level concurrency strategies often use a **Fetch-Modify-Save** approach:
1. Fetch current wallet: `SELECT balance FROM wallets WHERE id = :id` -> `100.00`
2. Calculate new balance in Python: `new_balance = 100.00 + 1.00` -> `101.00`
3. Save back to database: `UPDATE wallets SET balance = 101.00 WHERE id = :id`

At high concurrency ($N \ge 500$), multiple concurrent threads/processes will fetch the *same* initial state (e.g., `100.00`) before any can save their updates. Consequently, they all write back `101.00`, causing the **"Lost Update"** problem.

### The Solution: Atomic SQL Updates
To prevent this, this API uses database-level row locks and MVCC (Multi-Version Concurrency Control) via atomic operations. Instead of computing the new balance in Python, we compile the update down to an atomic SQL calculation:

```sql
UPDATE wallets 
SET balance = balance + :delta, 
    version = version + 1 
WHERE id = :id
RETURNING id, balance, version;
```

#### Why it survives 500+ concurrent writes:
1. **Row-Level Locking:** PostgreSQL automatically acquires a row-level `EXCLUSIVE` lock on the updated row when executing the `UPDATE` query. Any other concurrent updates on that specific row will queue up and wait until the lock is released (after commit).
2. **Single Transaction Execution:** The check constraint `balance >= 0` is checked by PostgreSQL immediately during update execution. If an overdraft attempt occurs, PostgreSQL raises an `IntegrityError`, causing the database transaction to rollback immediately.
3. **No Lost Updates:** Because PostgreSQL processes updates to a row sequentially, each update reads the *latest committed* state of the row, avoiding any lost updates.

---

## Project Structure

```
.
├── Dockerfile
├── README.md
├── app
│   ├── database.py   # DB configuration (connection pooling)
│   ├── main.py       # FastAPI application & endpoints
│   └── models.py     # SQLAlchemy 2.0 models & constraints
├── docker-compose.yml
├── requirements.txt
└── tests
    └── load_test.py  # Asynchronous load test script (500 concurrent requests)
```

---

## Getting Started

### Prerequisites
* Docker and Docker Compose installed.

### Spin up the Containers
Run the following command to start PostgreSQL and the FastAPI application:

```bash
docker compose up --build -d
```

This will:
1. Start a PostgreSQL instance on port `5432`.
2. Wait for Postgres to be healthy.
3. Start the FastAPI application on port `8000`.
4. Automatically create the necessary database table (`wallets`) with the `chk_wallet_balance_positive` check constraint.

### Run the Concurrency Load Test
Once the services are running, run the load test script from your local machine to verify the API's behavior under 500+ concurrent writes:

1. (Optional) Install dependencies locally:
   ```bash
   pip install -r requirements.txt
   ```
2. Run the load test script:
   ```bash
   python tests/load_test.py
   ```

The script will:
1. Create a new wallet with an initial balance of `0.00` (version: `1`).
2. Fire `500` concurrent `PATCH` requests of `+1.00` each using `asyncio.gather`.
3. Assert that the final balance is exactly `500.00` and the version is exactly `501`.
