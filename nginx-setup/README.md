# nginx Setup for Go-Kart Race Control

This directory contains the nginx configuration to serve the Go-Kart application over HTTPS.

## Quick Setup

1. Run the install script as root:
   ```bash
   sudo ./install.sh
   ```
   
   The script will:
   - Check if you're running as root
   - Ask for your site name (e.g., gokart.wautier.eu)
   - Install nginx if needed
   - Create and enable the site configuration

2. Update SSL certificate paths in the generated configuration file:
   ```bash
   sudo vi /etc/nginx/sites-available/YOUR_SITE_NAME
   ```
   Update these lines:
   ```
   ssl_certificate /path/to/your/wautier.eu.crt;
   ssl_certificate_key /path/to/your/wautier.eu.key;
   ```

3. Reload nginx:
   ```bash
   sudo systemctl reload nginx
   ```

## Manual Setup

If you prefer to set up manually:

```bash
# Copy configuration
sudo cp gokart.wautier.eu /etc/nginx/sites-available/

# Enable site
sudo ln -s /etc/nginx/sites-available/gokart.wautier.eu /etc/nginx/sites-enabled/

# Edit SSL certificate paths
sudo vi /etc/nginx/sites-available/gokart.wautier.eu

# Test configuration
sudo nginx -t

# Reload nginx
sudo systemctl reload nginx
```

## Django Settings

Add these to your Django settings for HTTPS:

```python
# Force HTTPS in production
SECURE_SSL_REDIRECT = True
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')

# Allow nginx proxy
ALLOWED_HOSTS = ['gokart.wautier.eu', 'localhost', '127.0.0.1']
```

## Features

- Automatic HTTP to HTTPS redirect
- WebSocket support for Django Channels
- Static file serving with caching
- Security headers
- SSL/TLS best practices
- Large file upload support (100MB)

## Ports

- nginx: 80 (HTTP redirect) and 443 (HTTPS)  
- Django: 8000 (internal only)

Make sure your Django application is running on port 8000 for this configuration to work.