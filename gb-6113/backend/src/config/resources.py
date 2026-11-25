from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from .settings import DATABASE_URL, REDIS_URL
from redis import Redis

if DATABASE_URL.startswith("sqlite"):
    # The API serves sync endpoints from a small thread pool.  A file/in-memory
    # SQLite database is nevertheless useful for local and CI exercise.
    engine_kwargs = {
        "pool_pre_ping": True,
        "connect_args": {"check_same_thread": False},
    }
    if ":memory:" in DATABASE_URL or DATABASE_URL in {"sqlite://", "sqlite+pysqlite://"}:
        engine_kwargs["poolclass"] = StaticPool
    engine = create_engine(DATABASE_URL, **engine_kwargs)
else:
    engine = create_engine(DATABASE_URL, pool_pre_ping=True)
cache = Redis.from_url(REDIS_URL, socket_connect_timeout=2, socket_timeout=3)
