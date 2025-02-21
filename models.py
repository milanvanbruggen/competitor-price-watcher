from sqlalchemy import Column, Integer, String, JSON, DateTime, Index
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

class ConfigVersion(Base):
    __tablename__ = "config_versions"

    id = Column(Integer, primary_key=True, index=True)
    config_type = Column(String)  # 'domain', 'country', or 'package'
    config_id = Column(String)    # domain name, country code, or package id
    config = Column(JSON)
    version = Column(Integer)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    comment = Column(String, nullable=True)

    __table_args__ = (
        # Composite index voor sneller zoeken van versies
        Index('idx_config_versions_type_id_version', 'config_type', 'config_id', 'version'),
    ) 