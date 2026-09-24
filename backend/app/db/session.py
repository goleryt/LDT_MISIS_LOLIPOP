from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.core.config import get_settings

engine = create_engine(get_settings().database_url, pool_pre_ping=True, pool_size=5, max_overflow=10,
                       connect_args={"connect_timeout": 5, "options": "-c statement_timeout=60000"})
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
