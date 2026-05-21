import os
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

# Use asyncpg driver for asynchronous PostgreSQL communication
DATABASE_URL = os.getenv(
    "DATABASE_URL", 
    "postgresql+asyncpg://postgres:postgres@db:5432/walletdb"
)

# Optimize pool parameters for high-velocity concurrent writes
# pool_size=20, max_overflow=0 as requested
engine = create_async_engine(
    DATABASE_URL,
    pool_size=20,
    max_overflow=0,
    pool_pre_ping=True,
    echo=False
)

SessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False
)

async def get_db():
    """Dependency to provide DB session per request and handle cleanup."""
    async with SessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()
