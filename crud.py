from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
import models
import schemas

# Domain Config operations
def get_domain_config(db: Session, domain: str):
    return db.query(models.DomainConfig).filter(models.DomainConfig.domain == domain).first()

def get_domain_configs(db: Session, skip: int = 0, limit: int = 100):
    return db.query(models.DomainConfig).offset(skip).limit(limit).all()

def create_domain_config(db: Session, config: schemas.DomainConfigCreate):
    db_config = models.DomainConfig(**config.dict())
    try:
        db.add(db_config)
        db.commit()
        db.refresh(db_config)
        return db_config
    except IntegrityError:
        db.rollback()
        # Update existing config
        db_config = db.query(models.DomainConfig).filter(models.DomainConfig.domain == config.domain).first()
        for key, value in config.dict().items():
            setattr(db_config, key, value)
        db.commit()
        db.refresh(db_config)
        return db_config

def delete_domain_config(db: Session, domain: str):
    db_config = db.query(models.DomainConfig).filter(models.DomainConfig.domain == domain).first()
    if db_config:
        db.delete(db_config)
        db.commit()
        return True
    return False

# Country Config operations
def get_country_config(db: Session, country_code: str):
    return db.query(models.CountryConfig).filter(models.CountryConfig.country_code == country_code).first()

def get_country_configs(db: Session, skip: int = 0, limit: int = 100):
    return db.query(models.CountryConfig).offset(skip).limit(limit).all()

def create_country_config(db: Session, config: schemas.CountryConfigCreate):
    db_config = models.CountryConfig(**config.dict())
    try:
        db.add(db_config)
        db.commit()
        db.refresh(db_config)
        return db_config
    except IntegrityError:
        db.rollback()
        # Update existing config
        db_config = db.query(models.CountryConfig).filter(models.CountryConfig.country_code == config.country_code).first()
        for key, value in config.dict().items():
            setattr(db_config, key, value)
        db.commit()
        db.refresh(db_config)
        return db_config

def delete_country_config(db: Session, country_code: str):
    db_config = db.query(models.CountryConfig).filter(models.CountryConfig.country_code == country_code).first()
    if db_config:
        db.delete(db_config)
        db.commit()
        return True
    return False

# Package Config operations
def get_package_config(db: Session, package_id: str):
    return db.query(models.PackageConfig).filter(models.PackageConfig.package_id == package_id).first()

def get_package_configs(db: Session, skip: int = 0, limit: int = 100):
    return db.query(models.PackageConfig).offset(skip).limit(limit).all()

def create_package_config(db: Session, config: schemas.PackageConfigCreate):
    db_config = models.PackageConfig(**config.dict())
    try:
        db.add(db_config)
        db.commit()
        db.refresh(db_config)
        return db_config
    except IntegrityError:
        db.rollback()
        # Update existing config
        db_config = db.query(models.PackageConfig).filter(models.PackageConfig.package_id == config.package_id).first()
        for key, value in config.dict().items():
            setattr(db_config, key, value)
        db.commit()
        db.refresh(db_config)
        return db_config

def delete_package_config(db: Session, package_id: str):
    db_config = db.query(models.PackageConfig).filter(models.PackageConfig.package_id == package_id).first()
    if db_config:
        db.delete(db_config)
        db.commit()
        return True
    return False 