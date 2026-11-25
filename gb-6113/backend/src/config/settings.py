import os

DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///./workbench-dev.db")
REDIS_URL = os.environ.get("REDIS_URL", "redis://127.0.0.1:6379/0")
JWT_SECRET = os.environ.get("JWT_SECRET", "local-development-only-change-me")
DEMO_PASSWORD = os.environ.get("DEMO_PASSWORD", "Demo-DbWorkbench-2026")
SEED_DEMO = os.environ.get("SEED_DEMO", "true").lower() == "true"
