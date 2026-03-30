from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy import event, text
import os

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./data/trading_bot.db")

# Convert sqlite:/// to sqlite+aiosqlite:///
if DATABASE_URL.startswith("sqlite:///"):
    DATABASE_URL = DATABASE_URL.replace("sqlite:///", "sqlite+aiosqlite:///", 1)

engine = create_async_engine(
    DATABASE_URL,
    echo=False,
    pool_pre_ping=True,
    connect_args={"timeout": 30},
)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


async def init_db():
    os.makedirs("data", exist_ok=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # Enable WAL mode for concurrent read/write access
        await conn.execute(text("PRAGMA journal_mode=WAL"))
        await conn.execute(text("PRAGMA busy_timeout=5000"))


async def get_db():
    async with async_session() as session:
        yield session
