from sqlalchemy import create_engine, inspect
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
import os
from config import IS_PRODUCTION, LOCAL_DATABASE_URL

# In production, use PostgreSQL from Fly.io. In development, use local database
if IS_PRODUCTION:
    # Fly.io automatically injects the DATABASE_URL environment variable
    DATABASE_URL = os.getenv("DATABASE_URL")
    if DATABASE_URL and DATABASE_URL.startswith("postgres://"):
        # SQLAlchemy 1.4+ requires postgresql:// instead of postgres://
        DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)
    if not DATABASE_URL:
        raise ValueError("DATABASE_URL environment variable is required in production")
else:
    DATABASE_URL = LOCAL_DATABASE_URL

print(f"Using database: {DATABASE_URL}")

# Create SQLAlchemy engine
engine = create_engine(DATABASE_URL)

# Create SessionLocal class
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Create Base class
Base = declarative_base()

# Initialize database
def init_db():
    # Import all models here to avoid circular imports
    from models import DomainConfig, CountryConfig, PackageConfig, ConfigVersion
    
    # Check if tables exist
    inspector = inspect(engine)
    existing_tables = inspector.get_table_names()
    
    # Only create tables that don't exist yet
    if not all(table in existing_tables for table in ['domain_configs', 'country_configs', 'package_configs', 'config_versions']):
        Base.metadata.create_all(bind=engine)
        print("Created missing database tables")
    else:
        print("All database tables already exist")

# Dependency
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close() 