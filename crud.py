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
        # Sla versie op
        save_config_version(db, 'domain', config.domain, config.config)
        return db_config
    except IntegrityError:
        db.rollback()
        # Update bestaande config
        db_config = db.query(models.DomainConfig).filter(models.DomainConfig.domain == config.domain).first()
        for key, value in config.dict().items():
            setattr(db_config, key, value)
        db.commit()
        db.refresh(db_config)
        # Sla versie op
        save_config_version(db, 'domain', config.domain, config.config)
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
        # Sla versie op
        save_config_version(db, 'country', config.country_code, config.config)
        return db_config
    except IntegrityError:
        db.rollback()
        # Update bestaande config
        db_config = db.query(models.CountryConfig).filter(models.CountryConfig.country_code == config.country_code).first()
        for key, value in config.dict().items():
            setattr(db_config, key, value)
        db.commit()
        db.refresh(db_config)
        # Sla versie op
        save_config_version(db, 'country', config.country_code, config.config)
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
        # Sla versie op
        save_config_version(db, 'package', config.package_id, config.config)
        return db_config
    except IntegrityError:
        db.rollback()
        # Update bestaande config
        db_config = db.query(models.PackageConfig).filter(models.PackageConfig.package_id == config.package_id).first()
        for key, value in config.dict().items():
            setattr(db_config, key, value)
        db.commit()
        db.refresh(db_config)
        # Sla versie op
        save_config_version(db, 'package', config.package_id, config.config)
        return db_config

def delete_package_config(db: Session, package_id: str):
    db_config = db.query(models.PackageConfig).filter(models.PackageConfig.package_id == package_id).first()
    if db_config:
        db.delete(db_config)
        db.commit()
        return True
    return False

def save_config_version(db: Session, config_type: str, config_id: str, config: dict, comment: str = None):
    """Sla een nieuwe versie op van een configuratie en behoud maximaal 5 versies"""
    
    # Haal bestaande versies op
    existing_versions = db.query(models.ConfigVersion).filter(
        models.ConfigVersion.config_type == config_type,
        models.ConfigVersion.config_id == config_id
    ).order_by(models.ConfigVersion.version.desc()).all()
    
    # Bepaal nieuwe versie nummer
    new_version = 1 if not existing_versions else existing_versions[0].version + 1
    
    # Maak nieuwe versie
    db_version = models.ConfigVersion(
        config_type=config_type,
        config_id=config_id,
        config=config,
        version=new_version,
        comment=comment
    )
    db.add(db_version)
    
    # Verwijder oudste versie als er meer dan 5 zijn
    if len(existing_versions) >= 5:
        db.delete(existing_versions[-1])
    
    db.commit()
    return db_version

def get_config_versions(db: Session, config_type: str, config_id: str, skip: int = 0, limit: int = 5):
    """Haal alle versies op van een configuratie"""
    return db.query(models.ConfigVersion).filter(
        models.ConfigVersion.config_type == config_type,
        models.ConfigVersion.config_id == config_id
    ).order_by(models.ConfigVersion.version.desc()).offset(skip).limit(limit).all()

def restore_config_version(db: Session, config_type: str, config_id: str, version: int):
    """Herstel een specifieke versie van een configuratie"""
    # Zoek de versie
    db_version = db.query(models.ConfigVersion).filter(
        models.ConfigVersion.config_type == config_type,
        models.ConfigVersion.config_id == config_id,
        models.ConfigVersion.version == version
    ).first()
    
    if not db_version:
        return None
        
    # Update de huidige configuratie
    if config_type == 'domain':
        config = create_domain_config(db, schemas.DomainConfigCreate(
            domain=config_id,
            config=db_version.config
        ))
    elif config_type == 'country':
        config = create_country_config(db, schemas.CountryConfigCreate(
            country_code=config_id,
            config=db_version.config
        ))
    elif config_type == 'package':
        config = create_package_config(db, schemas.PackageConfigCreate(
            package_id=config_id,
            config=db_version.config
        ))
    else:
        return None
        
    return config 