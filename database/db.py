from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy import Column, BigInteger, Integer, String, Boolean, Float, DateTime, ForeignKey
from sqlalchemy.future import select
from sqlalchemy import delete
import datetime
import os
import logging
from dotenv import load_dotenv

load_dotenv()

# Use DATABASE_URL if available (Render), fallback to SQLite locally
DATABASE_URL = os.getenv("DATABASE_URL")

if DATABASE_URL:
    # SQLAlchemy requires 'postgresql+asyncpg://' for async postgres
    if DATABASE_URL.startswith("postgres://"):
        DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql+asyncpg://", 1)
    elif DATABASE_URL.startswith("postgresql://"):
        DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://", 1)
    
    # asyncpg does not support 'sslmode', swap it with 'ssl'
    if "sslmode=" in DATABASE_URL:
        DATABASE_URL = DATABASE_URL.replace("sslmode=", "ssl=")
    
    logging.info(f"Using PostgreSQL database")
    engine = create_async_engine(DATABASE_URL, echo=False, pool_pre_ping=True)

else:
    DATABASE_URL = "sqlite+aiosqlite:///./database/bot.db"
    logging.info("Using local SQLite database")
    engine = create_async_engine(DATABASE_URL, echo=False)

AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
Base = declarative_base()

class User(Base):
    __tablename__ = "users"
    user_id = Column(BigInteger, primary_key=True)  # Telegram IDs can exceed 32-bit int
    username = Column(String, nullable=True)
    is_premium = Column(Boolean, default=False)
    joined_at = Column(DateTime, default=datetime.datetime.utcnow)

class Alert(Base):
    __tablename__ = "alerts"
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, ForeignKey("users.user_id"))  # Match BigInteger
    coin_id = Column(String)
    symbol = Column(String)
    target_price = Column(Float)
    condition = Column(String)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

async def add_user(user_id: int, username: str):
    async with AsyncSessionLocal() as session:
        async with session.begin():
            user = await session.get(User, user_id)
            if not user:
                new_user = User(user_id=user_id, username=username)
                session.add(new_user)
        await session.commit()

async def is_premium(user_id: int) -> bool:
    async with AsyncSessionLocal() as session:
        user = await session.get(User, user_id)
        return user.is_premium if user else False

async def add_alert(user_id: int, coin_id: str, symbol: str, target_price: float, condition: str):
    async with AsyncSessionLocal() as session:
        async with session.begin():
            new_alert = Alert(
                user_id=user_id,
                coin_id=coin_id,
                symbol=symbol,
                target_price=target_price,
                condition=condition
            )
            session.add(new_alert)
        await session.commit()

async def get_all_alerts():
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(Alert))
        alerts = result.scalars().all()
        return [(a.id, a.user_id, a.coin_id, a.symbol, a.target_price, a.condition, a.created_at) for a in alerts]

async def get_user_alerts(user_id: int):
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(Alert).where(Alert.user_id == user_id))
        alerts = result.scalars().all()
        return [(a.id, a.user_id, a.coin_id, a.symbol, a.target_price, a.condition, a.created_at) for a in alerts]

async def delete_alert(alert_id: int):
    async with AsyncSessionLocal() as session:
        async with session.begin():
            await session.execute(delete(Alert).where(Alert.id == alert_id))
        await session.commit()
