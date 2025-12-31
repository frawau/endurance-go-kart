#!/bin/bash

# GoKartRace Manager
# One script to rule them all - manage services, SSL certificates and deployment modes

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="$SCRIPT_DIR/.env"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

log_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Load environment variables
if [ -f "$ENV_FILE" ]; then
    source "$ENV_FILE"
else
    log_error ".env file not found!"
    exit 1
fi

show_help() {
    echo "GoKartRace Manager - One Script to Rule Them All"
    echo ""
    echo "Usage: $0 [command]"
    echo ""
    echo "Service Management:"
    echo "  start           Start application (HTTP mode)"
    echo "  stop            Stop all services"
    echo "  restart         Restart services with current configuration"
    echo "  logs            Show service logs"
    echo "  status          Show current configuration and service status"
    echo ""
    echo "SSL Management:"
    echo "  enable-acme     Enable automatic SSL with Let's Encrypt"
    echo "  enable-manual   Enable manual SSL (provide your own certificates)"
    echo "  disable-ssl     Disable SSL (HTTP only mode)"
    echo "  generate-cert   Generate SSL certificate (acme mode only)"
    echo "  install-cert    Install manual SSL certificates"
    echo ""
    echo "Utility:"
    echo "  help            Show this help message"
    echo ""
    echo "Examples:"
    echo "  $0 start                    # Start in HTTP mode"
    echo "  $0 enable-acme              # Configure automatic SSL"
    echo "  $0 generate-cert            # Generate Let's Encrypt certificate"
    echo ""
}

show_status() {
    log_info "Current SSL Configuration:"
    echo "  SSL_MODE: ${SSL_MODE:-none (commented out)}"
    echo "  APP_DOMAIN: ${APP_DOMAIN:-not set}"
    echo "  SSL_EMAIL: ${SSL_EMAIL:-not set}"

    if [ -f "ssl/fullchain.pem" ] && [ -f "ssl/privkey.pem" ]; then
        log_success "SSL certificates found in ./ssl/"
    else
        log_warning "No SSL certificates found in ./ssl/"
    fi

    # Check if acme.sh service is running
    if docker ps | grep -q acme_sh; then
        log_success "acme.sh service is running"
    else
        log_info "acme.sh service is not running"
    fi
}

enable_acme() {
    log_info "Enabling automatic SSL with acme.sh..."

    # Update .env file
    sed -i 's/^# SSL_MODE=.*/SSL_MODE=acme/' "$ENV_FILE"
    sed -i 's/^# SSL_EMAIL=.*/SSL_EMAIL='"${SSL_EMAIL:-admin@$APP_DOMAIN}"'/' "$ENV_FILE"
    sed -i 's/^# ACME_CHALLENGE=.*/ACME_CHALLENGE=http/' "$ENV_FILE"

    log_success "SSL mode set to 'acme'"
    log_info "To apply changes, run: $0 restart"
    log_info "To generate certificate, run: $0 generate-cert"
}

enable_manual() {
    log_info "Enabling manual SSL..."

    # Update .env file
    sed -i 's/^# SSL_MODE=.*/SSL_MODE=manual/' "$ENV_FILE"
    sed -i 's/^# SSL_EMAIL=.*/SSL_EMAIL='"${SSL_EMAIL:-admin@$APP_DOMAIN}"'/' "$ENV_FILE"

    log_success "SSL mode set to 'manual'"
    log_warning "You need to provide SSL certificates in ./ssl/ directory"
    log_info "Required files: ./ssl/fullchain.pem and ./ssl/privkey.pem"
    log_info "To install certificates, run: $0 install-cert"
}

disable_ssl() {
    log_info "Disabling SSL..."

    # Comment out SSL configuration in .env
    sed -i 's/^SSL_MODE=.*$/# SSL_MODE=none/' "$ENV_FILE"
    sed -i 's/^SSL_EMAIL=.*$/# SSL_EMAIL=admin@your-domain.com/' "$ENV_FILE"
    sed -i 's/^ACME_CHALLENGE=.*$/# ACME_CHALLENGE=http/' "$ENV_FILE"

    log_success "SSL disabled"
    log_info "To apply changes, run: $0 restart"
}

start_services() {
    log_info "Starting GoKartRace application..."
    docker compose up -d
    log_success "Services started!"
    log_info "Application available at: http://${APP_DOMAIN}:${APP_PORT}"
}

stop_services() {
    log_info "Stopping all services..."
    docker compose --profile ssl-acme down
    log_success "All services stopped!"
}

show_logs() {
    log_info "Showing service logs (press Ctrl+C to exit)..."
    docker compose logs -f
}

generate_cert() {
    if [ "${SSL_MODE}" != "acme" ]; then
        log_error "Certificate generation only available in 'acme' mode"
        log_info "Run '$0 enable-acme' first"
        exit 1
    fi

    if [ -z "${SSL_EMAIL}" ]; then
        log_error "SSL_EMAIL not set in .env file"
        log_info "Please add: SSL_EMAIL=your-email@example.com"
        exit 1
    fi

    log_info "Starting services with acme.sh profile..."
    docker compose --profile ssl-acme up -d

    log_info "Waiting for services to start..."
    sleep 5

    log_info "Configuring acme.sh to use Let's Encrypt..."
    docker compose exec acme-sh acme.sh --set-default-ca --server letsencrypt

    log_info "Registering account with Let's Encrypt (${SSL_EMAIL})..."
    docker compose exec acme-sh acme.sh --register-account -m "${SSL_EMAIL}"

    log_info "Generating SSL certificate for ${APP_DOMAIN}..."
    docker compose exec acme-sh acme.sh --issue -d "${APP_DOMAIN}" --webroot /var/www/certbot

    if [ $? -eq 0 ]; then
        log_info "Installing certificate..."
        docker compose exec acme-sh acme.sh --install-cert -d "${APP_DOMAIN}" \
            --cert-file /etc/ssl/certs/cert.pem \
            --key-file /etc/ssl/certs/privkey.pem \
            --fullchain-file /etc/ssl/certs/fullchain.pem \
            --reloadcmd "docker restart nginx"

        log_success "SSL certificate generated and installed!"
        log_info "Restarting nginx to enable HTTPS..."
        docker compose restart nginx
        log_success "HTTPS is now enabled at https://${APP_DOMAIN}"
    else
        log_error "Certificate generation failed!"
        log_info "Check that:"
        log_info "  - ${APP_DOMAIN} points to this server"
        log_info "  - Port 80 is accessible from the internet"
        log_info "  - No firewall is blocking the connection"
        log_info "  - DNS propagation is complete (try: nslookup ${APP_DOMAIN})"
        exit 1
    fi
}

install_cert() {
    log_info "Installing manual SSL certificates..."

    if [ ! -f "ssl/fullchain.pem" ] || [ ! -f "ssl/privkey.pem" ]; then
        log_error "SSL certificates not found!"
        log_info "Please place your certificates in:"
        log_info "  ./ssl/fullchain.pem"
        log_info "  ./ssl/privkey.pem"
        exit 1
    fi

    # Copy certificates to docker volume
    docker run --rm -v "$(pwd)/ssl:/source" -v "ssl_certs:/dest" alpine \
        sh -c "cp /source/*.pem /dest/"

    log_success "SSL certificates installed!"
    log_info "Restarting services..."
    docker compose restart nginx
}

restart_services() {
    log_info "Restarting services with current configuration..."

    if [ "${SSL_MODE}" = "acme" ]; then
        log_info "Starting with acme.sh profile..."
        docker compose --profile ssl-acme down
        docker compose --profile ssl-acme up -d
    else
        docker compose down
        docker compose up -d
    fi

    log_success "Services restarted!"
}

# Main command handling
case "${1:-help}" in
    "start")
        start_services
        ;;
    "stop")
        stop_services
        ;;
    "restart")
        restart_services
        ;;
    "logs")
        show_logs
        ;;
    "status")
        show_status
        ;;
    "enable-acme")
        enable_acme
        ;;
    "enable-manual")
        enable_manual
        ;;
    "disable-ssl")
        disable_ssl
        ;;
    "generate-cert")
        generate_cert
        ;;
    "install-cert")
        install_cert
        ;;
    "help"|*)
        show_help
        ;;
esac