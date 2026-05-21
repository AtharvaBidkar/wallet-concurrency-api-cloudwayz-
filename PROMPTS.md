# AI Interaction Log (PROMPTS.md)

This log documents the prompts, the refinement loops resolving critical concurrency and data integrity traps, and the AI blindspots observed during development.

---

## 1. The Architecture Prompt

The initial architecture prompt sent to the AI was:

```text
Role: Senior Backend Architect. Task: Build a High-Velocity Wallet REST API that survives 500+ concurrent writes to a single record without data loss or corruption.

Tech Stack:
Framework: FastAPI (Asynchronous).
Database: PostgreSQL.
ORM: SQLAlchemy 2.0 (Async mode).
Containerization: Docker & Docker Compose.

Domain Model:
A Wallet table with id (UUID), balance (Numeric 12, 2), and version (Integer).
Add a SQL-level CheckConstraint('balance >= 0') to ensure no overdrafts.

Endpoints to Implement:
POST /wallets: Initialize a new wallet with a balance.
GET /wallets/{id}: Fetch current balance.
PATCH /wallets/{id}/credit: Apply a positive or negative delta to the balance.

Concurrency Strategy (Mandatory):
NO 'Fetch-Modify-Save' logic in Python.
DO use an Atomic SQL Update using SQLAlchemy's update() construct with an F-expression style increment (e.g., SET balance = balance + :delta, version = version + 1).
This ensures the database handles the row-level lock and prevents the "Lost Update" problem at N=500.

Deliverables to Generate:
app/main.py: The FastAPI application logic.
app/database.py: Async engine configuration with an optimized connection pool (set pool_size=20, max_overflow=0).
app/models.py: The SQLAlchemy schema.
tests/load_test.py: A script using httpx and asyncio.gather that creates a wallet, fires 500 concurrent credits of 1.0 each, and asserts the final balance is exactly 500.0.
docker-compose.yml: A setup with a Postgres image and the FastAPI app.
README.md: Explaining the choice of Atomic Updates + Postgres MVCC for high-velocity write safety.

Constraint: Ensure the response is clean, error-free, and production-ready.
```

---

## 2. The Refinement Loop

### Example 1: The Float Check (Preventing Rounding Errors)
* **Original Output**:
  ```python
  # Initial model proposal using floating point representation
  class Wallet(Base):
      __tablename__ = "wallets"
      id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
      balance: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
      version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
  ```
* **What was wrong**:
  Using `Float` for monetary calculations introduces binary floating-point representation errors (e.g., `0.1 + 0.2` resolving to `0.30000000000000004`). In financial applications, this leads to rounding inaccuracies and reconciliation discrepancies over time.
* **The Fix**:
  Refactored the schema and logic to use SQLAlchemy's `Numeric` column mapping to Python's `Decimal` type, guaranteeing exact decimal precision.
  ```python
  from decimal import Decimal
  from sqlalchemy import Numeric

  class Wallet(Base):
      __tablename__ = "wallets"
      id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
      balance: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, default=Decimal("0.00"))
      version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
  ```

### Example 2: The Transaction Check (Avoiding Read-Modify-Write)
* **Original Output**:
  ```python
  # Initial PATCH route using Python-level arithmetic
  @app.patch("/wallets/{id}/credit")
  async def credit_wallet(id: uuid.UUID, req: CreditRequest, db: AsyncSession = Depends(get_db)):
      wallet = await db.get(Wallet, id)
      if not wallet:
          raise HTTPException(404, "Wallet not found")
      wallet.balance += req.delta
      await db.commit()
      return wallet
  ```
* **What was wrong**:
  This uses a "Read-Modify-Write" pattern. Under high concurrency ($N=500$), multiple concurrent requests fetch the same original balance state simultaneously, calculate identical new balances in Python, and overwrite each other's updates. This causes major data loss (the "Lost Update" problem).
* **The Fix**:
  Refactored the update statement to run as a single atomic SQL F-expression (`SET balance = balance + :delta`). Row-level locking occurs within the database transaction, preventing lost updates.
  ```python
  stmt = (
      update(Wallet)
      .where(Wallet.id == id)
      .values(
          balance=Wallet.balance + req.delta,
          version=Wallet.version + 1
      )
      .returning(Wallet)
  )
  result = await db.execute(stmt)
  wallet = result.scalar_one_or_none()
  await db.commit()
  ```

### Example 3: The Overdraft Check (Database-level Constraint Enforcement)
* **Original Output**:
  ```python
  # Initial balance verification in application logic
  @app.patch("/wallets/{id}/credit")
  async def credit_wallet(id: uuid.UUID, req: CreditRequest, db: AsyncSession = Depends(get_db)):
      wallet = await db.get(Wallet, id)
      if wallet.balance + req.delta < 0:
          raise HTTPException(400, "Insufficient funds")
      ...
  ```
* **What was wrong**:
  Python-level checks create a Time-of-Check to Time-of-Use (TOCTOU) race condition. Multiple concurrent withdrawals could check the balance, see sufficient funds, and collectively withdraw more than the available balance, resulting in an overdraft.
* **The Fix**:
  Enforced the restriction via a SQL CheckConstraint `CheckConstraint("balance >= 0")` at the database level. Then, caught the database `IntegrityError` in the route handler and returned a clean HTTP 400 Bad Request.
  ```python
  # Model Constraint:
  __table_args__ = (
      CheckConstraint("balance >= 0", name="chk_wallet_balance_positive"),
  )

  # Main Route Handler:
  try:
      await db.execute(stmt)
      await db.commit()
  except IntegrityError:
      await db.rollback()
      raise HTTPException(status_code=400, detail="Insufficient funds")
  ```

---

## 3. The AI Blindspot Note

AI models consistently struggle with architectural traps surrounding concurrency and state validation. When asked to construct high-velocity web APIs, they default to standard web application paradigms (e.g., ORM state manipulation, read-then-write logic, and application-level authorization validation) without realizing that at $N=500$ concurrent requests, all application-level state checks are prone to race conditions. 

Additionally, AI models frequently overlook library-specific client-side limits during testing. For example, standard HTTPX test scripts default to a pool size of 100 connections. Without adjusting these limits on the client-side harness, the AI's load test silently queues requests locally, rendering the target server's concurrency behavior untested. Correcting these blindspots requires enforcing database-level constraints (locks, MVCC, check constraints) and matching client-side test harnesses to real concurrency parameters.
