from sqlalchemy import Column, Integer, String, JSON, DateTime
from sqlalchemy.sql import func
from database import Base

class DomainConfig(Base):
    __tablename__ = "domain_configs"

    id = Column(Integer, primary_key=True, index=True)
    domain = Column(String, unique=True, index=True)
    config = Column(JSON)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

class CountryConfig(Base):
    __tablename__ = "country_configs"

    id = Column(Integer, primary_key=True, index=True)
    country_code = Column(String, unique=True, index=True)
    config = Column(JSON)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

class PackageConfig(Base):
    __tablename__ = "package_configs"

    id = Column(Integer, primary_key=True, index=True)
    package_id = Column(String, unique=True, index=True)
    config = Column(JSON)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now()) 