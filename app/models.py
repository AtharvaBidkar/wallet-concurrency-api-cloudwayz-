import uuid
from decimal import Decimal
from sqlalchemy import Numeric, Integer, CheckConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

class Base(DeclarativeBase):
    pass

class Wallet(Base):
    __tablename__ = "wallets"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4
    )
    balance: Mapped[Decimal] = mapped_column(
        Numeric(precision=12, scale=2),
        nullable=False,
        default=Decimal("0.00")
    )
    version: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1
    )

    __table_args__ = (
        CheckConstraint("balance >= 0", name="chk_wallet_balance_positive"),
    )

    def __repr__(self) -> str:
        return f"<Wallet(id={self.id}, balance={self.balance}, version={self.version})>"
