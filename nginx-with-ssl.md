# SSL Implementation Plan for GoKartRace

## Architecture Overview

**Two-container approach:**
1. **acme.sh container** - Handles certificate generation/renewal
2. **nginx container** - Serves HTTPS with certificates

## Implementation Strategy

### 1. Certificate Generation Container
- Use `neilpang/acme.sh` Docker image
- Run as a separate service in docker-compose
- Generate certificates using DNS or HTTP-01 challenge
- Store certificates in shared volume
- Run certificate renewal as cron job

### 2. Nginx Configuration
- **Development mode**: HTTP only (current setup)
- **Production mode**: HTTPS with SSL certificates
- Conditional nginx config based on environment variable
- Redirect HTTP → HTTPS in production

### 3. Environment Variables
```bash
SSL_ENABLED=true|false
SSL_DOMAIN=your-domain.com
SSL_EMAIL=admin@your-domain.com
ACME_CHALLENGE=http|dns-cloudflare|dns-route53
```

### 4. Volume Strategy
```yaml
volumes:
  ssl_certs:/etc/ssl/certs
  nginx_conf:/etc/nginx/conf.d
```

### 5. Configuration Files
- **nginx-http.conf** (development)
- **nginx-https.conf** (production)
- **acme.sh config** for DNS providers

### 6. Startup Orchestration
1. acme.sh container starts first
2. Generates certificates if needed
3. nginx waits for certificates (depends_on + healthcheck)
4. nginx starts with appropriate config

## Challenges to Consider

1. **DNS Provider Integration** - Different APIs for different providers
2. **Certificate Renewal** - Nginx reload without downtime
3. **Initial Setup** - First-time certificate generation delay
4. **Domain Validation** - Ensuring domain points to server
5. **Fallback Strategy** - What if certificate generation fails?

## User Experience
- Single environment variable toggles SSL
- Automatic certificate generation on first run
- Transparent renewal process
- Clear error messages if setup fails

## Implementation Steps

### Phase 1: Basic SSL Setup
1. Add SSL environment variables to .env
2. Create conditional nginx configurations
3. Add acme.sh service to docker-compose
4. Create shared volumes for certificates

### Phase 2: Certificate Generation
1. Implement HTTP-01 challenge (simplest)
2. Add certificate generation script
3. Test certificate creation process
4. Implement nginx reload mechanism

### Phase 3: DNS Challenge Support
1. Add support for major DNS providers (Cloudflare, Route53)
2. Environment variable configuration for DNS APIs
3. Documentation for DNS setup

### Phase 4: Renewal & Monitoring
1. Automatic certificate renewal
2. Certificate expiry monitoring
3. Email notifications for failures
4. Health checks for SSL status

## Configuration Examples

### Docker Compose Addition
```yaml
acme-sh:
  image: neilpang/acme.sh
  container_name: acme_sh
  environment:
    - SSL_DOMAIN=${SSL_DOMAIN}
    - SSL_EMAIL=${SSL_EMAIL}
    - ACME_CHALLENGE=${ACME_CHALLENGE}
  volumes:
    - ssl_certs:/acme.sh
    - ./acme-config:/acme.sh/config
  command: daemon
  networks:
    - web_network
```

### Nginx SSL Config Template
```nginx
server {
    listen 443 ssl http2;
    server_name ${SSL_DOMAIN};

    ssl_certificate /etc/ssl/certs/${SSL_DOMAIN}/fullchain.cer;
    ssl_certificate_key /etc/ssl/certs/${SSL_DOMAIN}/${SSL_DOMAIN}.key;

    # SSL best practices
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers ECDHE-RSA-AES256-GCM-SHA512:DHE-RSA-AES256-GCM-SHA512:ECDHE-RSA-AES256-GCM-SHA384:DHE-RSA-AES256-GCM-SHA384;
    ssl_prefer_server_ciphers off;

    # HSTS
    add_header Strict-Transport-Security "max-age=63072000" always;

    location / {
        proxy_pass http://appseed-app:5005;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}

# HTTP redirect to HTTPS
server {
    listen 80;
    server_name ${SSL_DOMAIN};
    return 301 https://$server_name$request_uri;
}
```