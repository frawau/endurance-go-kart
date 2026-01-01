# GoKartRace - Endurance Go-Kart Championship Management System

<div align="center">
  <img src="static/logos/gokartrace-logo.png" alt="GoKartRace Logo" width="200"/>
</div>

A comprehensive Django-based management system for endurance go-kart races and championships with advanced race control features, penalty management, and hardware integration for stop-and-go penalty stations.

## 🏁 Features

### Race Management
- **Championship Management**: Create and manage multi-round championships with customizable settings
- **Round Configuration**: Flexible race setup with duration, pit lane timing, weight penalties, and driver change requirements
- **Team & Driver Management**: Comprehensive driver registration, team formation, and participant management
- **Real-time Race Control**: Live race monitoring with start/pause/resume controls and false start control.

### Penalty System
- **Multiple Penalty Types**:
  - **Stop & Go**: Traditional stop-and-go penalties with victim assignment
  - **Self Stop & Go**: No-victim penalties for self-imposed infractions  
  - **Laps Penalties**: Deduct laps from teams
  - **Post Race Laps**: Apply penalties after race completion
- **Penalty Configuration**: Championship-specific penalty setup with fixed/variable/per-hour options
- **Penalty Tracking**: Complete audit trail of imposed and served penalties

### Hardware Integration
- **Stop & Go Station**: Raspberry Pi-based penalty station with:
  - Physical button and sensor integration
  - Electronic fence control via I2C relays
  - Real-time display with countdown timers
  - HMAC-secured WebSocket communication
  - Automatic penalty completion detection

### Real-time Features
- **WebSocket Integration**: Live updates across all interfaces
- **Pit Lane Monitoring**: Real-time pit lane status and driver changes
- **Session Management**: Automatic driver session tracking and queue management
- **Live Dashboards**: Team carousels, penalty displays, and race information

### User Interface
- **Race Control Dashboard**: Comprehensive race director interface
- **Team Monitoring**: Individual team status and multi-team views
- **Driver Queue Management**: Real-time pending driver tracking
- **Penalty Management**: Intuitive penalty assignment and monitoring
- **Mobile-Responsive**: Works on all devices

### API & Integration
- **RESTful API**: Token-based authentication for external systems
- **QR Code Integration**: Driver and team scanning capabilities
- **Data Export**: Comprehensive race results and statistics
- **Multi-user Support**: Role-based access control (Race Directors, Queue Scanners, etc.)

## 🚀 Quick Start (TL;DR)

### Prerequisites
- Docker and Docker Compose
- Git
- Domain name (optional, for SSL/HTTPS)

### Installation in 3 Steps

```bash
# 1. Clone and navigate
git clone https://github.com/frawau/endurance-go-kart.git
cd endurance-go-kart

# 2. Create and configure .env file
cp .env.example .env               # Create .env from template
./race-manager.sh generate-secret  # Generate and add secure secrets to .env
# Edit .env: Set APP_DOMAIN, configure timezone, adjust other settings

# 3. Start the application
./race-manager.sh start
```

**That's it!** Access at `http://your-domain:5085`

Default login: `admin` / `admin` (change immediately!)

### Enable HTTPS (Optional)

```bash
./race-manager.sh enable-letsencrypt  # Configure Let's Encrypt
./race-manager.sh generate-cert        # Generate certificate
# Now available at https://your-domain.com
# Certificates auto-renew - zero maintenance!
```

---

## 📖 Detailed Installation Guide

### 🐳 Docker Installation (Recommended for Production)

For production deployment, Docker provides easier setup and consistent environment:

#### Prerequisites
- Docker and Docker Compose
- Git

#### Setup Steps

1. **Clone the repository**
   ```bash
   git clone https://github.com/frawau/endurance-go-kart.git
   cd endurance-go-kart
   ```

2. **Configure environment variables**

   Create your `.env` file from the template:
   ```bash
   cp .env.example .env
   ```

   Edit the `.env` file to match your setup:
   ```bash
   # Database settings
   POSTGRES_USER=gokart
   POSTGRES_PASSWORD=gokart
   POSTGRES_DB=gokart

   # Admin user (created automatically)
   DJANGO_SUPERUSER_USERNAME=admin
   DJANGO_SUPERUSER_PASSWORD=admin

   # Security keys (generate your own - see examples below!)
   SECRET_KEY=your-django-secret-key-change-this-to-something-random-and-secure
   STOPANDGO_HMAC_SECRET=your-hmac-secret-for-station-security-also-change-this

   # Your domain
   APP_DOMAIN=your-domain.com

   # HTTP port (optional, default: 5085 for HTTP-only, 80 for SSL modes)
   APP_PORT=5085

   # Timezone for all containers
   TZ=Asia/Bangkok
   ```

   **Port Configuration**:
   - **HTTP-only mode** (`SSL_MODE=none`): Uses `APP_PORT` (default: 5085) - good for development
   - **SSL modes** (`letsencrypt`, `acme`, `manual`): Automatically uses port 80 (required for Let's Encrypt) and 443
   - The race-manager.sh script handles port assignment automatically

   **Generate Secure Keys:**

   Use the race-manager script (recommended):

   ```bash
   ./race-manager.sh generate-secret
   ```

   This will generate three secure random secrets and automatically update your `.env` file:
   - `SECRET_KEY` - Django's cryptographic signing key
   - `STOPANDGO_HMAC_SECRET` - Hardware station authentication
   - `TIMING_HMAC_SECRET` - Timing daemon authentication (optional)

   **Alternative manual methods:**

   ```bash
   # Using OpenSSL
   openssl rand -base64 64

   # Using Python
   python -c "import secrets; print(secrets.token_urlsafe(64))"

   # Using online generator
   # Visit: https://djecrety.ir/ (Django-specific secret generator)
   ```

   **Important Security Notes:**
   - `SECRET_KEY`: Django's secret key for cryptographic signing. Generate a unique 50+ character random string
   - `STOPANDGO_HMAC_SECRET`: Used for secure communication with hardware penalty stations. **This same secret must be configured on your Stop & Go station hardware**
   - Change default admin credentials immediately after first login
   - Use strong, unique passwords for production deployments
   - **`.env` file is NOT tracked by git** - it's in `.gitignore` to protect your secrets
   - On production servers, `git pull` will never overwrite your `.env` file

3. **Start the application**

   Using race-manager (recommended):
   ```bash
   ./race-manager.sh start
   ```

   Or using Docker Compose directly:
   ```bash
   docker compose up -d
   ```

   The application will be available at `http://your-domain:5085`

4. **Initial setup and configuration**

   a. **Login with default admin**
      - Navigate to your site
      - Login with username: `admin`, password: `admin`

   b. **Change admin password**
      - Go to Admin menu → Administration
      - Change the admin user password

   c. **Create a new admin user**
      - In Django admin, go to Users
      - Add a new user with your preferred credentials
      - Assign the user to groups: `Admin` and `Race Director`

   d. **Switch to your new user**
      - Logout from the default admin account
      - Login with your new user credentials
      - You can now start configuring championships and races

#### Service Management

Using race-manager (recommended):

```bash
# View logs
./race-manager.sh logs

# Stop the application
./race-manager.sh stop

# Restart with current configuration
./race-manager.sh restart

# Check SSL and service status
./race-manager.sh status

# Update application after git pull
git pull
./race-manager.sh rebuild  # Rebuild container with new code
```

Using Docker Compose directly (advanced):

```bash
# View logs
docker compose logs -f

# Stop the application
docker compose down

# Reset database (removes all data)
docker compose down
docker volume rm endurance-go-kart_postgres_data
docker compose up -d

# Update application
git pull
docker compose down
docker compose up -d --build
```

#### Accessing the Database

```bash
# Connect to PostgreSQL container
docker exec -it postgres psql -U gokart -d gokart

# Backup database
docker exec postgres pg_dump -U gokart gokart > backup.sql

# Restore database
docker exec -i postgres psql -U gokart gokart < backup.sql
```

**When to use `rebuild` vs `restart`:**

- **`rebuild`** - Use after `git pull` or when you modify:
  - Python code (views.py, models.py, etc.)
  - Templates (HTML files)
  - Static files
  - requirements.txt
  - Any application code

- **`restart`** - Use when you only change:
  - .env file (environment variables)
  - Configuration settings (SSL_MODE, APP_DOMAIN, etc.)

The Dockerfile copies code into the image at build time, so code changes require rebuilding the container.

### 💻 Development Installation (Without Docker)

For local development or if you prefer not to use Docker:

#### Prerequisites
- Python 3.8+
- Django 4.2+
- Redis (for WebSocket support)
- PostgreSQL or SQLite

#### Installation

```bash
# Clone the repository
git clone https://github.com/frawau/endurance-go-kart.git
cd endurance-go-kart

# Create virtual environment
python -m venv env
source env/bin/activate  # On Windows: env\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Create .env file from template
cp .env.example .env

# Generate secrets (automatically updates .env)
./race-manager.sh generate-secret

# Set up database
python manage.py makemigrations
python manage.py migrate

# Create superuser
python manage.py createsuperuser

# Initialize database with sample data (optional)
python manage.py initialisedb

# Start the development server
python manage.py runserver
```

The application will be available at `http://127.0.0.1:8000`

---

### 🔒 SSL/HTTPS Configuration (Optional)

The application supports four SSL modes controlled by the `SSL_MODE` environment variable:

#### SSL Modes

1. **`none`** (Default) - HTTP only, no SSL
2. **`letsencrypt`** - Automatic SSL with Let's Encrypt (recommended)
   - Fully automated certificate generation and renewal
   - Certificates renew automatically every 60 days (90-day validity)
   - Zero maintenance required
3. **`acme`** - Automatic SSL with ZeroSSL (requires email registration)
   - Same automated renewal as Let's Encrypt
4. **`manual`** - Manual SSL (provide your own certificates)
   - You manage renewal yourself

#### Quick Setup with Race Manager (Recommended)

Use the included race manager script for easy SSL management:

```bash
# Start application (HTTP mode)
./race-manager.sh start

# Check current SSL status
./race-manager.sh status

# Enable automatic SSL with Let's Encrypt (recommended)
./race-manager.sh enable-letsencrypt  # Updates .env to SSL_MODE=letsencrypt
./race-manager.sh generate-cert       # Generates and installs certificate
# Your site is now available at https://your-domain.com

# Alternative: Enable automatic SSL with ZeroSSL
./race-manager.sh enable-acme         # Updates .env to SSL_MODE=acme
./race-manager.sh generate-cert       # Generates and installs certificate

# Enable manual SSL (provide your own certificates)
./race-manager.sh enable-manual       # Updates .env to SSL_MODE=manual
# Place certificates in ./ssl/fullchain.pem and ./ssl/privkey.pem
./race-manager.sh install-cert        # Installs certificates

# Disable SSL (back to HTTP only)
./race-manager.sh disable-ssl         # Updates .env to SSL_MODE=none
./race-manager.sh restart             # Applies changes

# Other useful commands
./race-manager.sh stop                # Stop all services
./race-manager.sh restart             # Restart with current configuration
./race-manager.sh logs                # View logs
```

#### Manual SSL Configuration

If you prefer to configure SSL manually without using `race-manager.sh`:

**For Automatic SSL (Let's Encrypt):**

1. Edit `.env`:
   ```bash
   SSL_MODE=letsencrypt
   APP_DOMAIN=your-domain.com
   SSL_EMAIL=admin@your-domain.com
   ```

2. Start services with acme.sh profile:
   ```bash
   docker compose --profile ssl-acme up -d
   ```

3. The race-manager.sh script handles certificate generation automatically, but if running manually:
   ```bash
   docker compose exec acme-sh acme.sh --set-default-ca --server letsencrypt
   docker compose exec acme-sh acme.sh --register-account -m admin@your-domain.com
   docker compose exec acme-sh acme.sh --issue -d your-domain.com --webroot /var/www/certbot
   docker compose exec acme-sh acme.sh --install-cert -d your-domain.com \
       --cert-file /etc/ssl/certs/cert.pem \
       --key-file /etc/ssl/certs/privkey.pem \
       --fullchain-file /etc/ssl/certs/fullchain.pem
   docker compose restart nginx
   ```

**For Automatic SSL (ZeroSSL):**

1. Edit `.env`:
   ```bash
   SSL_MODE=acme
   APP_DOMAIN=your-domain.com
   SSL_EMAIL=admin@your-domain.com
   ```

2. Follow the same steps as Let's Encrypt, but ZeroSSL doesn't require setting default CA

4. **For manual certificates**, place your files in `./ssl/`:
   - `fullchain.pem` - Full certificate chain
   - `privkey.pem` - Private key (**MUST be unencrypted/no passphrase**)

#### SSL Requirements

- **Private key must be unencrypted** - nginx cannot handle password-protected keys
- **Domain must point to your server** - required for Let's Encrypt validation
- **Port 80 must be accessible** - needed for HTTP ACME challenge

#### SSL Environment Variables

```bash
# SSL Configuration (uncomment to enable)
# SSL_MODE=none              # none|acme|manual
# SSL_EMAIL=admin@your-domain.com
#
# For manual mode
# SSL_CERT_PATH=./ssl/fullchain.pem
# SSL_KEY_PATH=./ssl/privkey.pem
#
# For acme.sh mode
# ACME_CHALLENGE=http        # http|dns-cloudflare|dns-route53
```

**Important**: The application automatically detects HTTP vs HTTPS and uses the appropriate WebSocket protocol (ws:// or wss://).

## 🏆 Championship Setup

1. **Create Championship**: Define championship parameters and rounds
2. **Configure Penalties**: Set up penalty types with values and options
3. **Register Teams**: Add teams and assign numbers
4. **Add Drivers**: Register drivers with photos and details
5. **Setup Rounds**: Configure race parameters and ready the round
6. **Race Control**: Use the race control interface to manage live races

## 🛠 Hardware Station Setup

For the Stop & Go penalty station:

```bash
# On Raspberry Pi
cd stations/
python stopandgo-station.py --button 18 --fence 36 --server your-domain.com -port 443
```

### Hardware Requirements
- Raspberry Pi with GPIO access (Tested on RPi Zero 2 W)
- Physical button (normally open)
- Fence sensor (optional, can be disabled) for area breach detections (e.g. early start)
- I2C relay board (optional) for, for example, flashing lights control
- Display (Required for status and countdown)

## 🔧 Configuration

### Environment Variables

```bash
# .env file
SECRET_KEY=your-django-secret-key
DEBUG=False
APP_DOMAIN=your-domain.com
STOPANDGO_HMAC_SECRET=your-hmac-secret-for-station-security

# Database (if using PostgreSQL)
DATABASE_URL=postgresql://user:password@localhost/gokartrace
```

### External Access Configuration

The system automatically detects internal vs external connections for the `agent_login` endpoint by checking if the client IP belongs to any local network interface. This ensures QR code URLs include the correct port:

- **Internal connections**: Return URLs without port (e.g., `https://domain.com/driver_queue/`)
- **External connections**: Return URLs with external port (e.g., `https://domain.com:8000/driver_queue/`)

No additional nginx configuration is required - the system uses network interface detection to determine connection source.

### Management Commands

```bash
# Reset round data
python manage.py roundreset

# Generate test data
python manage.py generate_teams 10
python manage.py generate_people 50

# Clear cache
python manage.py clearcache
```

## 📊 Features Not Yet Implemented

- **Lap Timing**: Individual lap time measurement and analysis
- **Live Timing Displays**: Real-time lap time leaderboards
- **Automatic Position Calculation**: Based on completed laps and timing

## 🏁 Race Control Interface

The main race control dashboard provides:
- Pre-race checks and validation
- Race start/pause/resume controls
- Live penalty assignment (Stop & Go, Laps)
- Real-time driver queue monitoring
- Pit lane status monitoring
- System message logging

## 🔐 Security Features

- Token-based API authentication
- HMAC-signed hardware communication
- Role-based access control
- CSRF protection
- Secure WebSocket connections

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add tests if applicable
5. Submit a pull request

## 📝 License

This project is licensed under the MIT License - see the LICENSE file for details.

## 🆘 Support

For support and questions:
- Create an issue on GitHub
- Check existing documentation
- Review the management commands for database operations

## 🏎 Built For Racing

This system has been designed and tested for real endurance go-kart championships, providing the reliability and features needed for professional race management while remaining accessible for smaller events.

---

**Note**: This system excels at race management, team coordination, and penalty administration. For complete timing solutions, consider integrating with dedicated lap timing hardware and software.
