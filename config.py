import os

# Environment settings
ENV = os.getenv('ENV', 'development')  # 'development' or 'production'
IS_PRODUCTION = ENV == 'production'

# Browser settings
HEADLESS = IS_PRODUCTION  # True in production, False in development 