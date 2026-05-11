'''
Database schema and async helpers.

Privacy guarantee: prompt and response content is NEVER stored.
Only token counts (integers) from the llama-server usage field are recorded.
'''

import os
import secrets
from datetime import datetime, timezone

import bcrypt
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy import (
    BigInteger, DateTime, ForeignKey, Integer, String, Text
)

# SQLite (used in tests) requires INTEGER for autoincrement primary keys;
# PostgreSQL uses BIGINT. This variant handles both transparently.
_PK = BigInteger().with_variant(Integer, 'sqlite')

DATABASE_URL = os.environ["DATABASE_URL"]

# SQLite (used in tests) doesn't support pool_size/max_overflow
_is_sqlite = DATABASE_URL.startswith('sqlite')
engine = create_async_engine(
    DATABASE_URL,
    **({} if _is_sqlite else {"pool_size": 10, "max_overflow": 20}),
)


class Base(DeclarativeBase):
    '''Base class for SQLAlchemy models.'''


class User(Base):
    '''Registered API user. Holds the hashed key, paid token balance,
    and relationships to trials, usage, and purchases.'''

    __tablename__ = 'users'

    id: Mapped[int] = mapped_column(_PK, primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    api_key_hash: Mapped[str] = mapped_column(Text, nullable=False)
    api_key_prefix: Mapped[str] = mapped_column(String(12), nullable=False)
    balance_tokens: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc),
        server_default='now()'
    )

    trial_tokens: Mapped[list['TrialTokens']] = relationship(back_populates='user')
    usage_events: Mapped[list['UsageEvent']] = relationship(back_populates='user')
    purchases: Mapped[list['TokenPurchase']] = relationship(back_populates='user')


class TrialTokens(Base):
    '''A trial grant. Tokens are available if:
      - expires_at > now  (not yet expired)
      - remaining_tokens > 0
    activated_at is set on first use; if NULL and expires_at < now, the grant
    was never used (useful for campaign analytics - no PII involved).'''

    __tablename__ = 'trial_tokens'

    id: Mapped[int] = mapped_column(_PK, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(_PK, ForeignKey('users.id'), nullable=False)
    tokens_granted: Mapped[int] = mapped_column(BigInteger, nullable=False)
    remaining_tokens: Mapped[int] = mapped_column(BigInteger, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc),
        server_default='now()'
    )

    user: Mapped['User'] = relationship(back_populates='trial_tokens')


class UsageEvent(Base):
    '''One row per completed inference request.
    NO prompt text, NO response text - only token counts.'''

    __tablename__ = 'usage_events'

    id: Mapped[int] = mapped_column(_PK, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(_PK, ForeignKey('users.id'), nullable=False)

    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc),
        server_default='now()'
    )

    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    model: Mapped[str] = mapped_column(Text, nullable=False, default='')

    user: Mapped['User'] = relationship(back_populates='usage_events')


class TokenPurchase(Base):
    '''Record of a completed payment. payment_ref is the Stripe session id
    or BTCPay invoice id and must be unique (idempotency key).'''

    __tablename__ = 'token_purchases'

    id: Mapped[int] = mapped_column(_PK, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(_PK, ForeignKey('users.id'), nullable=False)

    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc),
        server_default='now()'
    )

    payment_method: Mapped[str] = mapped_column(
        Text, nullable=False, default='stripe'  # 'stripe' | 'btcpay'
    )

    payment_ref: Mapped[str] = mapped_column(
        Text, unique=True, nullable=False # Stripe session id or BTCPay invoice id
    )

    tokens_added: Mapped[int] = mapped_column(BigInteger, nullable=False)
    amount_cents: Mapped[int] = mapped_column(Integer, nullable=False)

    user: Mapped['User'] = relationship(back_populates='purchases')


# ── Schema creation ──────────────────────────────────────────────────────────

async def init_db() -> None:
    '''Create all tables if they don't exist. Safe to call on every startup.'''

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


# ── Auth helpers ─────────────────────────────────────────────────────────────

def generate_api_key() -> tuple[str, str, str]:
    '''Generate a new API key.

    Returns:
        A tuple of (raw_key, key_hash, key_prefix). raw_key is shown to
        the user exactly once and never stored. key_hash is stored in the
        database. key_prefix (first 12 chars) is stored for display.
    '''

    raw = "sk-" + secrets.token_urlsafe(32)
    key_hash = bcrypt.hashpw(raw.encode(), bcrypt.gensalt()).decode()
    prefix = raw[:12]

    return raw, key_hash, prefix


def verify_api_key(raw_key: str, key_hash: str) -> bool:
    '''Check a raw API key against the stored bcrypt hash.

    Args:
        raw_key: The raw API key submitted by the client.
        key_hash: The bcrypt hash stored in the database.

    Returns:
        True if the key matches, False otherwise.
    '''

    return bcrypt.checkpw(raw_key.encode(), key_hash.encode())


# ── Balance helpers ──────────────────────────────────────────────────────────

async def get_user_by_key_prefix(session: AsyncSession, prefix: str) -> User | None:
    '''Fetch the user whose api_key_prefix matches prefix.

    Uses a fast SQL pre-filter before the bcrypt comparison in calling code.

    Args:
        session: Active SQLAlchemy async session.
        prefix: First 12 characters of the API key.

    Returns:
        The matching User, or None if not found.
    '''

    result = await session.execute(
        text("SELECT * FROM users WHERE api_key_prefix = :prefix"),
        {"prefix": prefix},
    )

    rows = result.mappings().all()

    if not rows:
        return None

    # There should only ever be one, but handle duplicates defensively
    from sqlalchemy import select
    stmt = select(User).where(User.api_key_prefix == prefix)
    users = (await session.execute(stmt)).scalars().all()

    return users[0] if users else None


async def get_active_trial_tokens(session: AsyncSession, user_id: int) -> int:
    '''Sum remaining_tokens across all non-expired trial grants for a user.

    Args:
        session: Active SQLAlchemy async session.
        user_id: Primary key of the user.

    Returns:
        Total remaining trial tokens (0 if none active).
    '''

    now = datetime.now(timezone.utc)
    result = await session.execute(
        text(
            "SELECT COALESCE(SUM(remaining_tokens), 0) FROM trial_tokens "
            "WHERE user_id = :uid AND expires_at > :now AND remaining_tokens > 0"
        ),
        {"uid": user_id, "now": now},
    )

    return result.scalar()


async def deduct_tokens(
    session: AsyncSession, user: User, total_tokens: int
) -> None:
    '''Deduct tokens from trial balance first, then paid balance.

    Modifies trial grant rows and the user's balance_tokens in place.
    Does not commit; the caller is responsible for committing.

    Args:
        session: Active SQLAlchemy async session.
        user: The User ORM object whose balance will be reduced.
        total_tokens: Total number of tokens to deduct.
    '''

    now = datetime.now(timezone.utc)

    # Deduct from active trial grants (oldest first)
    if total_tokens > 0:
        result = await session.execute(
            text(
                "SELECT id, remaining_tokens FROM trial_tokens "
                "WHERE user_id = :uid AND expires_at > :now AND remaining_tokens > 0 "
                "ORDER BY expires_at ASC"
            ),
            {"uid": user.id, "now": now},
        )

        trial_rows = result.mappings().all()

        for row in trial_rows:
            if total_tokens <= 0:
                break

            deduct = min(total_tokens, row["remaining_tokens"])
            await session.execute(
                text(
                    "UPDATE trial_tokens SET remaining_tokens = remaining_tokens - :d, "
                    "activated_at = COALESCE(activated_at, :now) "
                    "WHERE id = :id"
                ),
                {"d": deduct, "now": now, "id": row["id"]},
            )

            total_tokens -= deduct

    # Deduct remainder from paid balance
    if total_tokens > 0:
        await session.execute(
            text("UPDATE users SET balance_tokens = balance_tokens - :d WHERE id = :id"),
            {"d": total_tokens, "id": user.id},
        )

        user.balance_tokens -= total_tokens


async def total_available_tokens(session: AsyncSession, user: User) -> int:
    '''Return total tokens available: paid balance plus active trial tokens.

    Args:
        session: Active SQLAlchemy async session.
        user: The User ORM object.

    Returns:
        Sum of balance_tokens and all non-expired trial remaining_tokens.
    '''

    trial = await get_active_trial_tokens(session, user.id)
    return user.balance_tokens + trial
