from contextlib import asynccontextmanager
from decimal import Decimal
import uuid
from fastapi import FastAPI, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import update, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError

from app.database import engine, get_db
from app.models import Base, Wallet

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Initialize the tables on startup
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    # Cleanup / close connections on shutdown
    await engine.dispose()

app = FastAPI(
    title="High-Velocity Wallet REST API",
    description="An API that handles high-velocity write operations safely using Atomic SQL Updates.",
    version="1.0.0",
    lifespan=lifespan
)

# Schemas
class WalletCreate(BaseModel):
    balance: Decimal = Field(default=Decimal("0.00"), ge=0, decimal_places=2)

class WalletResponse(BaseModel):
    id: uuid.UUID
    balance: Decimal
    version: int

    model_config = {
        "from_attributes": True
    }

class CreditRequest(BaseModel):
    delta: Decimal = Field(..., decimal_places=2)

@app.post("/wallets", response_model=WalletResponse, status_code=status.HTTP_201_CREATED)
async def create_wallet(wallet_in: WalletCreate, db: AsyncSession = Depends(get_db)):
    """Initialize a new wallet with an initial balance."""
    wallet = Wallet(balance=wallet_in.balance)
    db.add(wallet)
    try:
        await db.commit()
        await db.refresh(wallet)
        return wallet
    except Exception as e:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Could not create wallet: {str(e)}"
        )

@app.get("/wallets/{id}", response_model=WalletResponse)
async def get_wallet(id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    """Fetch current balance and version."""
    stmt = select(Wallet).where(Wallet.id == id)
    result = await db.execute(stmt)
    wallet = result.scalar_one_or_none()
    if not wallet:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Wallet not found"
        )
    return wallet

@app.patch("/wallets/{id}/credit", response_model=WalletResponse)
async def credit_wallet(id: uuid.UUID, req: CreditRequest, db: AsyncSession = Depends(get_db)):
    """
    Apply a positive or negative delta to the balance.
    No Fetch-Modify-Save logic is used in Python. We perform an Atomic SQL Update.
    """
    stmt = (
        update(Wallet)
        .where(Wallet.id == id)
        .values(
            balance=Wallet.balance + req.delta,
            version=Wallet.version + 1
        )
        .returning(Wallet)
    )
    
    try:
        result = await db.execute(stmt)
        wallet = result.scalar_one_or_none()
        if not wallet:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Wallet not found"
            )
        await db.commit()
        return wallet
    except IntegrityError:
        await db.rollback()
        # This occurs when CheckConstraint fails (balance < 0)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Transaction failed: Insufficient funds (balance cannot be negative)."
        )
    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Unexpected database error: {str(e)}"
        )
