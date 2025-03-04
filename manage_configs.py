import argparse
from database import SessionLocal
from config_manager import export_configs_to_file, import_configs_from_file

def main():
    parser = argparse.ArgumentParser(description='Manage configurations')
    parser.add_argument('action', choices=['export', 'import'], help='Action to perform')
    parser.add_argument('--file', default='configs_backup.json', help='File to export to or import from')
    parser.add_argument('--clear', action='store_true', help='Clear existing configurations before importing')
    
    args = parser.parse_args()
    
    db = SessionLocal()
    try:
        if args.action == 'export':
            print(f"Exporting configurations to {args.file}...")
            export_configs_to_file(db, args.file)
            print("Export completed successfully!")
        else:  # import
            print(f"Importing configurations from {args.file}...")
            import_configs_from_file(db, args.file, args.clear)
            print("Import completed successfully!")
    finally:
        db.close()

if __name__ == '__main__':
    main() 