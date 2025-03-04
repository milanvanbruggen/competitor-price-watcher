import json
from datetime import datetime, timezone
from typing import Dict, List, Optional
from sqlalchemy.orm import Session
from models import DomainConfig, CountryConfig, PackageConfig, ConfigVersion

def export_configs(db: Session) -> Dict:
    """
    Export all configurations from the database to a dictionary.
    """
    # Get all configurations
    domain_configs = db.query(DomainConfig).all()
    country_configs = db.query(CountryConfig).all()
    package_configs = db.query(PackageConfig).all()
    config_versions = db.query(ConfigVersion).all()

    # Convert to dictionaries
    export_data = {
        "domain_configs": [
            {
                "domain": config.domain,
                "config": config.config,
                "created_at": config.created_at.isoformat() if config.created_at else None,
                "updated_at": config.updated_at.isoformat() if config.updated_at else None
            }
            for config in domain_configs
        ],
        "country_configs": [
            {
                "country_code": config.country_code,
                "config": config.config,
                "created_at": config.created_at.isoformat() if config.created_at else None,
                "updated_at": config.updated_at.isoformat() if config.updated_at else None
            }
            for config in country_configs
        ],
        "package_configs": [
            {
                "package_id": config.package_id,
                "config": config.config,
                "created_at": config.created_at.isoformat() if config.created_at else None,
                "updated_at": config.updated_at.isoformat() if config.updated_at else None
            }
            for config in package_configs
        ],
        "config_versions": [
            {
                "config_type": config.config_type,
                "config_id": config.config_id,
                "config": config.config,
                "version": config.version,
                "created_at": config.created_at.isoformat() if config.created_at else None,
                "comment": config.comment
            }
            for config in config_versions
        ]
    }

    return export_data

def save_configs_to_file(export_data: Dict, filename: str = "configs_backup.json"):
    """
    Save the exported configurations to a JSON file.
    """
    with open(filename, 'w') as f:
        json.dump(export_data, f, indent=2)

def load_configs_from_file(filename: str = "configs_backup.json") -> Dict:
    """
    Load configurations from a JSON file.
    """
    with open(filename, 'r') as f:
        return json.load(f)

def import_configs(configs: Dict[str, List[Dict]], db: Session, clear_existing: bool = False):
    """Import configurations from a dictionary containing lists of configs for each type."""
    try:
        if clear_existing:
            # Delete all existing configurations
            db.query(DomainConfig).delete()
            db.query(CountryConfig).delete()
            db.query(PackageConfig).delete()
            db.commit()

        # Process domain configurations
        for domain_config in configs.get('domain_configs', []):
            domain = domain_config.get('domain')
            if domain:
                # Check if domain exists
                existing = db.query(DomainConfig).filter(DomainConfig.domain == domain).first()
                if existing:
                    # Update existing config
                    existing.config = domain_config.get('config', {})
                    existing.updated_at = datetime.now(timezone.utc)
                else:
                    # Create new config
                    new_config = DomainConfig(
                        domain=domain,
                        config=domain_config.get('config', {})
                    )
                    db.add(new_config)

        # Process country configurations
        for country_config in configs.get('country_configs', []):
            country_code = country_config.get('country_code')
            if country_code:
                # Check if country exists
                existing = db.query(CountryConfig).filter(CountryConfig.country_code == country_code).first()
                if existing:
                    # Update existing config
                    existing.config = country_config.get('config', {})
                    existing.updated_at = datetime.now(timezone.utc)
                else:
                    # Create new config
                    new_config = CountryConfig(
                        country_code=country_code,
                        config=country_config.get('config', {})
                    )
                    db.add(new_config)

        # Process package configurations
        for package_config in configs.get('package_configs', []):
            # Try to get package_id from either 'id' or 'package_id' field
            package_id = package_config.get('package_id') or package_config.get('id')
            if package_id:
                # Check if package exists
                existing = db.query(PackageConfig).filter(PackageConfig.package_id == str(package_id)).first()
                if existing:
                    # Update existing config
                    config_data = package_config.get('config', {})
                    if not config_data:  # If no config field, use the entire object
                        config_data = package_config
                    existing.config = config_data
                    existing.updated_at = datetime.now(timezone.utc)
                else:
                    # Create new config
                    config_data = package_config.get('config', {})
                    if not config_data:  # If no config field, use the entire object
                        config_data = package_config
                    new_config = PackageConfig(
                        package_id=str(package_id),
                        config=config_data
                    )
                    db.add(new_config)

        db.commit()
        return True
    except Exception as e:
        db.rollback()
        raise e

def export_configs_to_file(db: Session, filename: str = "configs_backup.json"):
    """
    Export all configurations to a file.
    """
    export_data = export_configs(db)
    save_configs_to_file(export_data, filename)

def import_configs_from_file(db: Session, filename: str = "configs_backup.json", clear_existing: bool = False):
    """
    Import configurations from a file.
    """
    import_data = load_configs_from_file(filename)
    import_configs(import_data, db, clear_existing) 