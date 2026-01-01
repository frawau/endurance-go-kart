#!/bin/bash

# SSL Setup Script for nginx
# This script configures nginx based on SSL_MODE environment variable

set -e

echo "SSL Setup: Configuring nginx for SSL_MODE=${SSL_MODE:-none}"

# Set default values
SSL_MODE=${SSL_MODE:-none}
APP_DOMAIN=${APP_DOMAIN:-localhost}

# Create nginx config directory
mkdir -p /etc/nginx/conf.d

# Remove any existing config
rm -f /etc/nginx/conf.d/default.conf

case "$SSL_MODE" in
    "none")
        echo "SSL Setup: Configuring HTTP-only mode"
        # Set variables for HTTP-only
        export ssl_redirect="no"

        # Process template for HTTP-only
        envsubst '${APP_DOMAIN} ${ssl_redirect}' < /etc/nginx/templates/default.conf.template > /tmp/nginx.conf

        # Remove HTTPS server block for HTTP-only mode
        sed '/# HTTPS server configuration/,/^}/d' /tmp/nginx.conf > /etc/nginx/conf.d/default.conf

        # Remove SSL redirect logic (no longer needed since we substitute it)
        # sed -i '/if ($ssl_redirect = "yes")/,/}/d' /etc/nginx/conf.d/default.conf
        ;;

    "letsencrypt"|"acme"|"manual")
        echo "SSL Setup: Configuring HTTPS mode (${SSL_MODE})"
        # Set variables for HTTPS
        export ssl_redirect="yes"

        # Process template for HTTPS
        envsubst '${APP_DOMAIN} ${ssl_redirect}' < /etc/nginx/templates/default.conf.template > /etc/nginx/conf.d/default.conf

        # Check if certificates exist
        if [ ! -f "/etc/ssl/certs/fullchain.pem" ] || [ ! -f "/etc/ssl/certs/privkey.pem" ]; then
            echo "SSL Setup: Warning - SSL certificates not found!"
            echo "SSL Setup: HTTPS server will not start until certificates are available"
            # Remove HTTPS server block temporarily
            sed '/# HTTPS server configuration/,/^}/d' /etc/nginx/conf.d/default.conf > /tmp/nginx-http.conf
            mv /tmp/nginx-http.conf /etc/nginx/conf.d/default.conf
            # Remove SSL redirect logic temporarily
            sed -i '/if ($ssl_redirect = "yes")/,/}/d' /etc/nginx/conf.d/default.conf
        else
            echo "SSL Setup: SSL certificates found - enabling HTTPS"
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