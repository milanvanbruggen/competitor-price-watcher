import os

# Environment settings
ENV = os.getenv('ENV', 'development')  # 'development' or 'production'
IS_PRODUCTION = ENV == 'production'

# Browser settings
HEADLESS = IS_PRODUCTION  # True in production, False in development
# HEADLESS = True

# Database settings
USE_POSTGRES_LOCALLY = os.getenv('USE_POSTGRES_LOCALLY', 'true').lower() == 'true'
LOCAL_DATABASE_URL = "postgresql://localhost/competitor_price_watcher" if USE_POSTGRES_LOCALLY else "sqlite:///./competitor_price_watcher.db" 