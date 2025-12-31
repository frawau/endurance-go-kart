# SSL Implementation Guide for GoKartRace

## Architecture Overview

**Two-container approach:**
1. **acme.sh container** - Handles certificate generation/renewal (supports Let's Encrypt and ZeroSSL)
2. **nginx container** - Serves HTTPS with certificates

## SSL Modes

The system supports four SSL modes controlled by the `SSL_MODE` environment variable:

1. **`none`** - HTTP only (default, no SSL)
2. **`letsencrypt`** - Automatic SSL with Let's Encrypt via acme.sh (recommended)
3. **`acme`** - Automatic SSL with ZeroSSL via acme.sh (requires email registration)
4. **`manual`** - Manual SSL (you provide your own certificates)

## Quick Start

### Automatic SSL with Let's Encrypt (Recommended)

```bash
# 1. Enable Let's Encrypt mode (updates .env)
./race-manager.sh enable-letsencrypt

# 2. Generate certificate
./race-manager.sh generate-cert

# Your site is now available at https://your-domain.com
```

### Automatic SSL with ZeroSSL (Alternative)

```bash
# 1. Enable ZeroSSL mode (updates .env)
./race-manager.sh enable-acme

# 2. Generate certificate
./race-manager.sh generate-cert

# Your site is now available at https://your-domain.com
```

### Environment Variables

Required in `.env` file:

```bash
SSL_MODE=letsencrypt                    # or 'acme', 'manual', or 'none'
APP_DOMAIN=your-domain.com              # Your domain name
SSL_EMAIL=admin@your-domain.com         # Email for certificate notifications
```

**Note**: The application runs on standard ports:
- Port 80 (HTTP) - Required for Let's Encrypt HTTP-01 challenge
- Port 443 (HTTPS) - Serves HTTPS traffic when SSL is enabled

## How It Works

### Certificate Generation Container (acme.sh)
- Uses official `neilpang/acme.sh` Docker image
- Supports both **Let's Encrypt** and **ZeroSSL** certificate authorities
- Generates certificates using HTTP-01 challenge
- Stores certificates in shared Docker volume
- Automatic renewal via daemon mode

### Nginx Configuration
- Reads `SSL_MODE` environment variable at startup
- **HTTP only mode** (`SSL_MODE=none`): Serves on port 80
- **HTTPS mode** (`SSL_MODE=letsencrypt`, `acme`, or `manual`): Serves on ports 80 and 443
  - Port 80: Redirects to HTTPS (except /.well-known/acme-challenge/)
  - Port 443: Serves HTTPS with SSL certificates

### Startup Orchestration
1. acme.sh container starts when `--profile ssl-acme` is used
2. `race-manager.sh generate-cert` configures certificate authority:
   - **letsencrypt mode**: Sets Let's Encrypt as CA, registers email
   - **acme mode**: Uses ZeroSSL (default), registers email
3. Generates certificate via HTTP-01 challenge
4. Installs certificates to shared volume
5. nginx automatically picks up certificates and enables HTTPS

## race-manager.sh Commands

The `race-manager.sh` script simplifies SSL management:

### Service Management
```bash
./race-manager.sh start           # Start application (HTTP mode)
./race-manager.sh stop            # Stop all services
./race-manager.sh restart         # Restart with current configuration
./race-manager.sh logs            # Show service logs
./race-manager.sh status          # Show SSL configuration status
```

### SSL Management
```bash
./race-manager.sh enable-letsencrypt  # Enable Let's Encrypt SSL (recommended)
./race-manager.sh enable-acme         # Enable ZeroSSL
./race-manager.sh enable-manual       # Enable manual SSL mode
./race-manager.sh disable-ssl         # Disable SSL (HTTP only)
./race-manager.sh generate-cert       # Generate certificate (auto-detects mode)
./race-manager.sh install-cert        # Install manual certificates
```

## Detailed Setup Guide

### Prerequisites

1. **Domain Name**: Your domain must point to your server's IP
   ```bash
   # Check DNS resolution
   nslookup your-domain.com
   ```

2. **Firewall**: Ports 80 and 443 must be accessible from the internet
   ```bash
   # Check if ports are open
   sudo ufw status
   sudo ufw allow 80/tcp
   sudo ufw allow 443/tcp
   ```

   **⚠️ Critical**: Port 80 is **required** for Let's Encrypt HTTP-01 challenge to verify domain ownership. The application now runs on standard port 80 (HTTP) and 443 (HTTPS), not on a custom port.

3. **Email Address**: Required for Let's Encrypt notifications

### Step-by-Step Setup

**1. Configure Environment Variables**

Edit `.env` file:
```bash
SSL_MODE=letsencrypt               # or 'acme' for ZeroSSL
APP_DOMAIN=your-domain.com
SSL_EMAIL=admin@your-domain.com
```

Or use the helper command:
```bash
./race-manager.sh enable-letsencrypt   # or enable-acme for ZeroSSL
# Then edit .env to set APP_DOMAIN and SSL_EMAIL
```

**2. Generate Certificate**

```bash
./race-manager.sh generate-cert
```

This command will:
- Start acme.sh container
- Configure certificate authority (Let's Encrypt or ZeroSSL based on SSL_MODE)
- Register your email
- Generate certificate via HTTP-01 challenge
- Install certificate
- Restart nginx with HTTPS enabled

**3. Verify HTTPS**

Visit your site:
```
https://your-domain.com
```

Check certificate:
```bash
openssl s_client -connect your-domain.com:443 -servername your-domain.com
```

### Manual SSL Setup

If you have your own certificates:

**1. Enable manual mode**
```bash
./race-manager.sh enable-manual
```

**2. Place certificates in `./ssl/` directory**
```bash
mkdir -p ssl
cp fullchain.pem ssl/
cp privkey.pem ssl/
```

**3. Install certificates**
```bash
./race-manager.sh install-cert
```

## Certificate Renewal

Let's Encrypt certificates are valid for 90 days. The acme.sh daemon automatically renews certificates when they have 60 days or less remaining.

**Check renewal status:**
```bash
docker compose exec acme-sh acme.sh --list
```

**Force renewal (for testing):**
```bash
docker compose exec acme-sh acme.sh --renew -d your-domain.com --force
docker compose restart nginx
```

## Troubleshooting

### Certificate Generation Fails

**Error**: "Verify error: Invalid response from http://your-domain.com/.well-known/acme-challenge/..."

**Solutions:**
1. Check DNS: `nslookup your-domain.com` (should point to your server)
2. Check firewall: Port 80 must be open
3. Check nginx is running: `docker ps | grep nginx`
4. Wait for DNS propagation (can take up to 48 hours)

**Error**: "Please add email address"

**Solution:**
Ensure `SSL_EMAIL` is set in `.env`:
```bash
SSL_EMAIL=admin@your-domain.com
```

### HTTPS Not Working After Certificate Generation

**Check certificates exist:**
```bash
docker compose exec nginx ls -la /etc/ssl/certs/
```

**Check nginx configuration:**
```bash
docker compose exec nginx cat /etc/nginx/conf.d/default.conf
```

**Restart nginx:**
```bash
docker compose restart nginx
```

### Port 443 Connection Refused

**Check nginx is listening on 443:**
```bash
docker compose exec nginx netstat -tlnp | grep 443
```

**Check firewall:**
```bash
sudo ufw status
sudo ufw allow 443/tcp
```

## Security Best Practices

The nginx configuration includes:

1. **Modern TLS protocols**: TLSv1.2 and TLSv1.3 only
2. **Strong ciphers**: ECDHE-RSA-AES256-GCM-SHA512 and similar
3. **HSTS**: Strict-Transport-Security header with 2-year max-age
4. **Security headers**: X-Frame-Options, X-Content-Type-Options
5. **HTTP to HTTPS redirect**: All HTTP traffic redirected to HTTPS

## WebSocket Support

WebSocket connections are fully supported over both HTTP and HTTPS:

- `ws://your-domain.com/ws/` (HTTP mode)
- `wss://your-domain.com/ws/` (HTTPS mode)

The nginx configuration automatically upgrades WebSocket connections and sets appropriate headers.

## Architecture Details

### Docker Volumes

```yaml
ssl_certs:/etc/ssl/certs          # Shared between acme-sh and nginx
acme_data:/acme.sh                # acme.sh working directory
acme_webroot:/var/www/certbot     # HTTP-01 challenge directory
```

### Docker Networks

```yaml
web_network:                       # nginx and acme-sh
db_network:                        # Django app, PostgreSQL, Redis
```

### Container Communication

```
Internet → nginx:80/443 → appseed_app:5005 → Django
                ↓
            acme.sh (certificate renewal)
```