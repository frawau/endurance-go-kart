#!/bin/bash

# SSL Setup Script for nginx
# This script configures nginx based on SSL_MODE environment variable

set -e

echo "SSL Setup: Configuring nginx for SSL_MODE=${SSL_MODE:-none}"

# Set default values
SSL_MODE=${SSL_MODE:-none}
APP_HOSTNAME=${APP_HOSTNAME:-localhost}

# Create nginx config directory
mkdir -p /etc/nginx/conf.d

# Remove any existing config
rm -f /etc/nginx/conf.d/default.conf

case "$SSL_MODE" in
    "none")
        echo "SSL Setup: Configuring HTTP-only mode"

        # Process template for HTTP-only
        envsubst '${APP_HOSTNAME} ${APP_PORT}' < /etc/nginx/templates/default.conf.template > /tmp/nginx.conf

        # Keep ssl_redirect as "no" (already default in template)

        # Remove HTTPS server block for HTTP-only mode
        sed '/# HTTPS server configuration/,/^}$/d' /tmp/nginx.conf > /etc/nginx/conf.d/default.conf
        ;;

    "letsencrypt"|"acme"|"manual")
        echo "SSL Setup: Configuring HTTPS mode (${SSL_MODE})"

        # Process template for HTTPS
        envsubst '${APP_HOSTNAME} ${APP_PORT}' < /etc/nginx/templates/default.conf.template > /tmp/nginx.conf

        # Set ssl_redirect to "yes" for SSL modes
        sed -i 's/default "no";/default "yes";/' /tmp/nginx.conf

        # Check if certificates exist
        if [ ! -f "/etc/ssl/certs/fullchain.pem" ] || [ ! -f "/etc/ssl/certs/privkey.pem" ]; then
            echo "SSL Setup: Warning - SSL certificates not found!"
            echo "SSL Setup: HTTPS server will not start until certificates are available"
            # Remove HTTPS server block temporarily
            sed '/# HTTPS server configuration/,/^}$/d' /tmp/nginx.conf > /etc/nginx/conf.d/default.conf
            # Remove SSL redirect logic temporarily
            sed -i 's/default "yes";/default "no";/' /etc/nginx/conf.d/default.conf
        else
            echo "SSL Setup: SSL certificates found - enabling HTTPS"
            mv /tmp/nginx.conf /etc/nginx/conf.d/default.conf
        fi
        ;;

    *)
        echo "SSL Setup: Error - Invalid SSL_MODE: $SSL_MODE"
        echo "SSL Setup: Valid options: none, letsencrypt, acme, manual"
        exit 1
        ;;
esac

echo "SSL Setup: Configuration complete"
echo "SSL Setup: Starting nginx..."

# Test nginx configuration
nginx -t

# Start nginx
exec nginx -g 'daemon off;'