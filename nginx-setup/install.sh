#!/bin/bash

# nginx setup script for Go-Kart Race Control

# Check if running as root
if [ "$EUID" -ne 0 ]; then
    echo "Error: This script must be run as root (use sudo)"
    echo "Usage: sudo ./install.sh"
    exit 1
fi

# Get site name from user
echo "nginx Setup for Go-Kart Race Control"
echo "====================================="
echo
read -p "Enter the site name (e.g., gokart.wautier.eu): " SITE_NAME

# Validate site name
if [ -z "$SITE_NAME" ]; then
    echo "Error: Site name cannot be empty"
    exit 1
fi

# Check if configuration template exists
if [ ! -f "gokart.wautier.eu" ]; then
    echo "Error: Configuration template 'gokart.wautier.eu' not found"
    echo "Make sure you're running this script from the nginx-setup directory"
    exit 1
fi

echo
echo "Setting up nginx for $SITE_NAME..."

# Check if nginx is installed
if ! command -v nginx &> /dev/null; then
    echo "Installing nginx..."
    apt update
    apt install -y nginx
fi

# Create configuration file with the specified site name
echo "Creating nginx configuration..."
sed "s/gokart\.wautier\.eu/$SITE_NAME/g" gokart.wautier.eu > "/etc/nginx/sites-available/$SITE_NAME"

# Enable the site
echo "Enabling site..."
ln -sf "/etc/nginx/sites-available/$SITE_NAME" "/etc/nginx/sites-enabled/"

# Remove default nginx site if it exists
if [ -f "/etc/nginx/sites-enabled/default" ]; then
    echo "Removing default nginx site..."
    rm /etc/nginx/sites-enabled/default
fi

# Test nginx configuration
echo "Testing nginx configuration..."
nginx -t

if [ $? -eq 0 ]; then
    echo
    echo "✅ nginx configuration test passed!"
    echo
else
    echo
    echo "❌ nginx configuration test failed! Please check the configuration."
    exit 1
fi

# Ask about systemd service installation
echo
read -p "Do you want to install the Django systemd service? (y/N): " INSTALL_SERVICE

if [[ "$INSTALL_SERVICE" =~ ^[Yy]$ ]]; then
    echo
    echo "Setting up Django systemd service..."
    
    # Get service configuration details
    read -p "Enter the username to run Django as [$USER]: " DJANGO_USER
    DJANGO_USER=${DJANGO_USER:-$USER}
    
    read -p "Enter the group to run Django as [$DJANGO_USER]: " DJANGO_GROUP
    DJANGO_GROUP=${DJANGO_GROUP:-$DJANGO_USER}
    
    read -p "Enter the full path to your Django project [$(pwd)/..]: " DJANGO_PATH
    DJANGO_PATH=${DJANGO_PATH:-$(pwd)/..}
    
    # Resolve absolute path
    DJANGO_PATH=$(realpath "$DJANGO_PATH")
    
    # Verify Django project exists
    if [ ! -f "$DJANGO_PATH/manage.py" ]; then
        echo "❌ Error: manage.py not found in $DJANGO_PATH"
        echo "Please check the Django project path"
        exit 1
    fi
    
    # Check if service template exists
    if [ ! -f "gokartrace.service.template" ]; then
        echo "❌ Error: Service template 'gokartrace.service.template' not found"
        exit 1
    fi
    
    # Create service file from template
    sed -e "s|__USER__|$DJANGO_USER|g" \
        -e "s|__GROUP__|$DJANGO_GROUP|g" \
        -e "s|__WORKDIR__|$DJANGO_PATH|g" \
        gokartrace.service.template > /etc/systemd/system/gokartrace.service
    
    # Reload systemd and enable service
    systemctl daemon-reload
    
    read -p "Enable and start the gokartrace service now? (y/N): " START_SERVICE
    
    if [[ "$START_SERVICE" =~ ^[Yy]$ ]]; then
        systemctl enable gokartrace.service
        systemctl start gokartrace.service
        echo "✅ Service enabled and started"
        
        # Show service status
        echo
        echo "Service status:"
        systemctl status gokartrace.service --no-pager -l
    else
        echo "Service created but not started. To start later:"
        echo "  systemctl enable gokartrace.service"
        echo "  systemctl start gokartrace.service"
    fi
    
    echo
    echo "Service file created: /etc/systemd/system/gokartrace.service"
fi

echo
echo "Setup Summary:"
echo "=============="
echo "✅ nginx site created: /etc/nginx/sites-available/$SITE_NAME"
if [[ "$INSTALL_SERVICE" =~ ^[Yy]$ ]]; then
    echo "✅ Django service created: /etc/systemd/system/gokartrace.service"
fi
echo
echo "Next steps:"
echo "1. Update SSL certificate paths in /etc/nginx/sites-available/$SITE_NAME"
echo "2. Run: systemctl reload nginx"
if [[ ! "$START_SERVICE" =~ ^[Yy]$ ]] && [[ "$INSTALL_SERVICE" =~ ^[Yy]$ ]]; then
    echo "3. Start Django service: systemctl start gokartrace.service"
fi
echo
echo "Your Django app will be accessible at: https://$SITE_NAME"