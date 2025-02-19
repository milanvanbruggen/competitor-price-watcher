import os
import json
from sqlalchemy.orm import Session
from database import SessionLocal, engine
import models
import glob

def migrate_domain_configs():
    db = SessionLocal()
    try:
        # Lees alle domain config bestanden
        config_files = glob.glob('config/domains/*.json')
        for config_file in config_files:
            with open(config_file) as f:
                config = json.load(f)
                domain = config['domain']
                
                # Maak nieuwe database entry
                db_config = models.DomainConfig(
                    domain=domain,
                    config=config
                )
                db.add(db_config)
                print(f"Migrated domain config: {domain}")
        
        db.commit()
    except Exception as e:
        print(f"Error migrating domain configs: {e}")
        db.rollback()
    finally:
        db.close()

def migrate_country_configs():
    db = SessionLocal()
    try:
        # Lees countries.json
        with open('config/countries.json') as f:
            countries = json.load(f)
            for country_code, config in countries.items():
                # Maak nieuwe database entry
                db_config = models.CountryConfig(
                    country_code=country_code,
                    config=config
                )
                db.add(db_config)
                print(f"Migrated country config: {country_code}")
        
        db.commit()
    except Exception as e:
        print(f"Error migrating country configs: {e}")
        db.rollback()
    finally:
        db.close()

def migrate_package_configs():
    db = SessionLocal()
    try:
        # Lees packages.json
        with open('config/packages.json') as f:
            packages = json.load(f)
            for package_id, config in packages['packages'].items():
                # Maak nieuwe database entry
                db_config = models.PackageConfig(
                    package_id=package_id,
                    config=config
                )
                db.add(db_config)
                print(f"Migrated package config: {package_id}")
        
        db.commit()
    except Exception as e:
        print(f"Error migrating package configs: {e}")
        db.rollback()
    finally:
        db.close()

if __name__ == "__main__":
    # Maak de database tabellen aan (voor het geval dat)
    models.Base.metadata.create_all(bind=engine)
    
    # Migreer alle configuraties
    print("Migrating domain configs...")
    migrate_domain_configs()
    
    print("\nMigrating country configs...")
    migrate_country_configs()
    
    print("\nMigrating package configs...")
    migrate_package_configs()
    
    print("\nMigration completed!") 