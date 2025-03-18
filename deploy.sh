#!/bin/bash

# Exit on error
set -e

# Check environment argument
if [ "$1" = "test" ]; then
    APP_NAME="competitor-price-watcher-test"
    CONFIG_FILE="fly_test.toml"
    VM_SIZE="shared-cpu-4x"
    DEPLOY_VM_SIZE="shared-cpu-1x"  # Smaller VM for deployment
    ENV_NAME="test"
elif [ "$1" = "prod" ]; then
    APP_NAME="competitor-price-watcher"
    CONFIG_FILE="fly.toml"
    VM_SIZE="shared-cpu-8x"
    DEPLOY_VM_SIZE="shared-cpu-4x"  # Smaller VM for deployment
    ENV_NAME="production"
else
    echo "Usage: $0 {test|prod} [--recreate]"
    echo "  test  - Deploy to test environment"
    echo "  prod  - Deploy to production environment"
    echo "  --recreate - Destroy and recreate the app"
    exit 1
fi

# Check if we should recreate the app
if [ "$2" = "--recreate" ]; then
    echo "Destroying existing app $APP_NAME..."
    fly apps destroy "$APP_NAME" -y
    sleep 30  # Wait for cleanup
fi

# Check if we're logged in
if ! fly auth whoami &> /dev/null; then
    echo "Please log in to Fly.io first:"
    echo "fly auth login"
    exit 1
fi

# Get current account
CURRENT_ACCOUNT=$(fly auth whoami)
echo "You are logged in as: $CURRENT_ACCOUNT"
read -p "Do you want to continue with this account? (y/n) " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "Please log in with the correct account first:"
    echo "fly auth login"
    exit 1
fi

# Get available organizations (skip header and separator lines)
echo "Fetching available organizations..."
ORGS=$(fly orgs list | grep -v -E "^(Name|----)" | awk '{print $2}')  # Use the Slug column, skip headers
if [ -z "$ORGS" ]; then
    echo "No organizations found. Please create an organization first."
    exit 1
fi

# If only one organization, use it automatically
if [ "$(echo "$ORGS" | wc -l)" -eq 1 ]; then
    SELECTED_ORG="$ORGS"
    echo "Using organization: $SELECTED_ORG"
else
    echo "Available organizations:"
    echo "$ORGS" | nl
    read -p "Select organization number: " ORG_NUM
    SELECTED_ORG=$(echo "$ORGS" | sed -n "${ORG_NUM}p")
fi

if [ -z "$SELECTED_ORG" ]; then
    echo "Invalid selection"
    exit 1
fi

echo "Selected organization: $SELECTED_ORG"

# Check if app exists
if fly apps list | grep -q "^$APP_NAME "; then
    echo "App $APP_NAME already exists"
else
    echo "Creating new app $APP_NAME..."
    fly launch --name "$APP_NAME" --region ams --org "$SELECTED_ORG" --copy-config --config "$CONFIG_FILE" --no-deploy
fi

# Check if database exists (improved check)
echo "Checking database status..."
DB_EXISTS=$(fly postgres list | grep -v -E "^(Name|----)" | awk '{print $1}' | grep -q "^$APP_NAME-db$" && echo "yes" || echo "no")
if [ "$DB_EXISTS" = "no" ]; then
    echo "Database $APP_NAME-db does not exist"
    read -p "Do you want to create it? (y/n) " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        echo "Creating database..."
        fly postgres create --name "$APP_NAME-db" --region ams --org "$SELECTED_ORG"
    else
        echo "Skipping database creation"
    fi
else
    echo "Database $APP_NAME-db exists"
fi

# Deploy the app with rolling update strategy
echo "Deploying app to $ENV_NAME environment..."
echo "Using rolling update strategy with longer timeouts..."
FLYCTL_TIMEOUT=900 fly deploy --config "$CONFIG_FILE" --app "$APP_NAME" --vm-size "$DEPLOY_VM_SIZE" --strategy rolling --no-cache

# Scale up the VM with retries
echo "Scaling up VM to production size..."
MAX_RETRIES=3
RETRY_COUNT=0
while [ $RETRY_COUNT -lt $MAX_RETRIES ]; do
    if fly scale vm "$VM_SIZE" --app "$APP_NAME"; then
        echo "VM scaled successfully"
        break
    else
        RETRY_COUNT=$((RETRY_COUNT + 1))
        if [ $RETRY_COUNT -lt $MAX_RETRIES ]; then
            echo "VM scaling failed, retrying in 30 seconds... (Attempt $RETRY_COUNT of $MAX_RETRIES)"
            sleep 30
        else
            echo "VM scaling failed after $MAX_RETRIES attempts"
            echo "You can try scaling manually later with:"
            echo "  fly scale vm $VM_SIZE --app $APP_NAME"
        fi
    fi
done

echo "Deployment complete!"
echo "App URL: https://$APP_NAME.fly.dev"
echo "Database commands:"
echo "  fly postgres connect -a $APP_NAME-db"
echo "  fly postgres logs -a $APP_NAME-db" 