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

### Transponder & Timing System
- **Transponder Management**: Dedicated CRUD interface for registering and managing transponders
  - Add/edit/delete transponders with descriptions and active status
  - Live scan detection: click "Scan" to listen for a transponder passing the loop and auto-fill its ID
  - Delete protection: transponders assigned to active races cannot be removed
- **Transponder Matching**: Assign transponders to teams for each race
  - Kart number auto-defaults to team number (user can override)
  - Scan button for quick transponder detection during assignment
  - Assignments auto-clone to dependent races (Q1 assignments carry forward to Q2, Q3, MAIN)
  - **Redundant transponders**: assign multiple transponders per team for hardware redundancy — a 7-second deduplication window ensures only one crossing per lap is counted; if all transponders miss a lap, the resulting suspicious lap is flagged in race control with a one-click split option
- **Qualifying Race Configuration**: Multi-session qualifying support
  - Configure 0-3 qualifying sessions (Q1, Q2, Q3) before the main race
  - Two qualifying ending modes: standard (before time) and F1-style (last lap after time)
  - Two grid methods: Best Time (combined best lap across sessions) and Elimination (knockout with cutoffs)
  - Per-session duration and cutoff configuration
  - Automatic creation of Race objects with correct dependencies (Q2 depends on Q1, MAIN depends on last Q)

### Hardware Integration
- **Stop & Go Station**: Raspberry Pi-based penalty station with:
  - Physical button and sensor integration
  - Electronic fence control via I2C relays
  - Real-time display with countdown timers
  - HMAC-secured WebSocket communication
  - Automatic penalty completion detection
- **Timing Station**: Transponder timing system with:
  - Plugin-based hardware support (TAG Heuer serial, Chronelec NetTag, simulator)
  - Multiple timing modes (interval, duration, time of day, decoder own time)
  - SQLite disk buffer with at-least-once delivery and ACK protocol
  - Native systemd service deployment
  - HMAC-secured WebSocket communication
  - Transponder scan broadcast: raw detections are forwarded to management/matching pages via WebSocket

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
./race-manager generate-secret  # Generate and add secure secrets to .env
# Edit .env: Set APP_HOSTNAME, configure timezone, adjust other settings

# 3. Start the application
./race-manager start
```

**That's it!** Access at `http://your-domain:5085`

Default login: `admin` / `admin` (change immediately!)

### Enable HTTPS (Optional)

```bash
./race-manager enable-letsencrypt  # Configure Let's Encrypt
./race-manager generate-cert        # Generate certificate
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
   APP_HOSTNAME=host.your-domain.com

   # HTTP port (optional, default: 5085 for HTTP-only, 80 for SSL modes)
   APP_PORT=5085

   # Timezone for all containers
   TZ=Asia/Bangkok
   ```

   **Port Configuration**:
   - **HTTP-only mode** (`SSL_MODE=none`): Uses `APP_PORT` (default: 5085) - good for development
   - **SSL modes** (`letsencrypt`, `acme`, `manual`): Automatically uses port 80 (required for Let's Encrypt) and 443
   - The race-manager script handles port assignment automatically

   **Generate Secure Keys:**

   Use the race-manager script (recommended):

   ```bash
   ./race-manager generate-secret
   ```

   This will generate three secure random secrets, update your `.env` file, and propagate
   the values into the station TOML config files automatically.
   - `SECRET_KEY` - Django's cryptographic signing key
   - `STOPANDGO_HMAC_SECRET` - Hardware station authentication
   - `TIMING_HMAC_SECRET` - Timing daemon authentication (optional)

   If you later change `.env` values manually (e.g. `APP_HOSTNAME`), re-run:
   ```bash
   ./race-manager configure-stations
   ```

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
   ./race-manager start
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
./race-manager logs

# Stop the application
./race-manager stop

# Restart with current configuration
./race-manager restart

# Check SSL and service status
./race-manager status

# Update application after git pull
git pull
./race-manager rebuild  # Rebuild container with new code
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
  - Configuration settings (SSL_MODE, APP_HOSTNAME, etc.)

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
./race-manager generate-secret

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
./race-manager start

# Check current SSL status
./race-manager status

# Enable automatic SSL with Let's Encrypt (recommended)
./race-manager enable-letsencrypt  # Updates .env to SSL_MODE=letsencrypt
./race-manager generate-cert       # Generates and installs certificate
# Your site is now available at https://your-domain.com

# Alternative: Enable automatic SSL with ZeroSSL
./race-manager enable-acme         # Updates .env to SSL_MODE=acme
./race-manager generate-cert       # Generates and installs certificate

# Enable manual SSL (provide your own certificates)
./race-manager enable-manual       # Updates .env to SSL_MODE=manual
# Place certificates in ./ssl/fullchain.pem and ./ssl/privkey.pem
./race-manager install-cert        # Installs certificates

# Disable SSL (back to HTTP only)
./race-manager disable-ssl         # Updates .env to SSL_MODE=none
./race-manager restart             # Applies changes

# Other useful commands
./race-manager stop                # Stop all services
./race-manager restart             # Restart with current configuration
./race-manager logs                # View logs
```

#### Manual SSL Configuration

If you prefer to configure SSL manually without using `race-manager`:

**For Automatic SSL (Let's Encrypt):**

1. Edit `.env`:
   ```bash
   SSL_MODE=letsencrypt
   APP_HOSTNAME=host.your-domain.com
   SSL_EMAIL=admin@your-domain.com
   ```

2. Start services with acme.sh profile:
   ```bash
   docker compose --profile ssl-acme up -d
   ```

3. The race-manager script handles certificate generation automatically, but if running manually:
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
   APP_HOSTNAME=host.your-domain.com
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

### Stop & Go Penalty Station

For the Stop & Go penalty station:

```bash
# On Raspberry Pi
cd stations/
python stopandgo-station.py --button 18 --fence 36 --server your-domain.com -port 443
```

#### Hardware Requirements
- Raspberry Pi with GPIO access (Tested on RPi Zero 2 W)
- Physical button (normally open)
- Fence sensor (optional, can be disabled) for area breach detections (e.g. early start)
- I2C relay board (optional) for, for example, flashing lights control
- Display (Required for status and countdown)

### Timing Station

The timing station relays transponder crossing events from decoder hardware to the Django app via WebSocket. It runs as a native systemd service on the host (not in Docker) because it needs direct LAN access to the timing decoder hardware.

#### Deployment

```bash
# Configure timing settings in .env
TIMING_PLUGIN_TYPE=nettag        # simulator|tag|nettag
TIMING_MODE=own_time             # interval|duration|time_of_day|own_time
TIMING_NETTAG_HOST=192.168.0.11  # NetTag: decoder IP address
TIMING_NETTAG_PORT=2009          # NetTag: decoder port
TIMING_NETTAG_PROTOCOL=udp       # NetTag: udp or tcp
TIMING_TAG_DEVICE=/dev/ttyUSB0   # TAG: serial device
TIMING_TAG_BAUD=9600             # TAG: baud rate

# Deploy as systemd service (creates venv, installs deps, generates config)
sudo ./race-manager deploy-timing

# Management
sudo ./race-manager timing-status      # Check service status
sudo ./race-manager undeploy-timing    # Stop and remove service
journalctl -u timing-station -f        # View logs
```

The `deploy-timing` command:
1. Creates a Python venv at `stations/timing/venv/`
2. Installs dependencies (websockets, toml, pyserial-asyncio)
3. Generates `timing-station.toml` from `.env` values via `configure-stations`
4. Installs and starts the systemd service

See `stations/timing/README.md` for detailed configuration and protocol documentation.

### NetTag UDP Proxy

When using a Chronelec decoder via a Lantronix serial-to-UDP converter, the Lantronix only supports a single remote endpoint. The NetTag proxy sits on the host machine, maintains the single upstream connection to the decoder, and fans out frames to multiple downstream clients (e.g., timing station and a test/logging system).

Each client gets its own buffered queue backed by SQLite (WAL mode). If a client falls behind or disconnects, frames accumulate and are replayed rapidly on reconnect.

**Port layout** when proxy and timing station are co-located:
- `:2009` — proxy upstream (receives from decoder)
- `:2010` — proxy downstream (sends frames to clients, receives ACKs)
- `:2011` — timing station (receives frames from proxy)

#### Setup

1. Edit `proxy/nettag-proxy.toml` with your decoder address and client list:
   ```toml
   [upstream]
   decoder_host = "192.168.0.11"
   decoder_port = 2009

   [downstream]
   listen_port = 2010
   resend_interval = 1.0

   [[client]]
   host = "127.0.0.1"
   port = 2011
   ```

2. Set the timing station to listen on a different port than the decoder:
   ```bash
   # In .env
   TIMING_NETTAG_PORT=2011
   ```

3. Deploy and start:
   ```bash
   sudo ./race-manager deploy-proxy
   sudo ./race-manager configure-stations
   sudo systemctl restart timing-station
   ```

#### Management

```bash
sudo ./race-manager deploy-proxy      # Install and start systemd service
./race-manager proxy-status            # Check service status
sudo ./race-manager undeploy-proxy    # Stop and remove service
journalctl -u nettag-proxy -f         # View logs
```

## 🔧 Configuration

### Environment Variables

```bash
# .env file
SECRET_KEY=your-django-secret-key
DEBUG=False
APP_HOSTNAME=host.your-domain.com
STOPANDGO_HMAC_SECRET=your-hmac-secret-for-station-security

# Database (if using PostgreSQL)
DATABASE_URL=postgresql://user:password@localhost/gokartrace
```

### External Access Configuration

The system automatically detects internal vs external connections for the `agent_login` endpoint by checking if the client IP belongs to any local network interface. This ensures QR code URLs include the correct port:

- **Internal connections**: Return URLs without port (e.g., `https://domain.com/driver_queue/`)
- **External connections**: Return URLs with external port (e.g., `https://domain.com:8000/driver_queue/`)

No additional nginx configuration is required - the system uses network interface detection to determine connection source.

### Management Commands (For Testing/Development)

#### Using race-manager (Recommended)

The easiest way to run Django management commands:

```bash
# Generate complete test data (RECOMMENDED - all-in-one)
./race-manager manage generate_test_data
# This creates: 30 teams, 150 drivers, 1 championship, 4 rounds, and team assignments

# Customize the number of teams and drivers
./race-manager manage generate_test_data --teams 50 --people 200

# Individual commands (if you need granular control)
./race-manager manage generate_teams --number 30
./race-manager manage generate_people --number 150
./race-manager manage initialisedb  # Requires teams and people first!

# Other useful commands
./race-manager manage roundreset     # Reset round data
./race-manager manage clearcache     # Clear Django cache
```

#### Using Docker Compose Directly (Advanced)

If you prefer not to use race-manager:

```bash
# Generate complete test data
docker compose exec appseed-app python manage.py generate_test_data

# Customize the number of teams and drivers
docker compose exec appseed-app python manage.py generate_test_data --teams 50 --people 200

# Individual commands
docker compose exec appseed-app python manage.py generate_teams --number 30
docker compose exec appseed-app python manage.py generate_people --number 150
docker compose exec appseed-app python manage.py initialisedb
```

#### On Development (Without Docker)

If running locally without Docker:

```bash
source env/bin/activate  # Activate virtual environment first

# All-in-one test data generation
python manage.py generate_test_data

# Or individual commands
python manage.py generate_teams --number 30
python manage.py generate_people --number 150
python manage.py initialisedb
```

**Important**:
- Run these on the VM/server where Docker is deployed, not on your local machine
- **Use `./race-manager manage`** for easiest execution
- **Use `generate_test_data`** for easiest setup - it runs all commands in the correct order

## 📊 Features Not Yet Implemented

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

**Note**: This system handles race management, team coordination, penalty administration, and transponder-based lap timing with support for TAG Heuer and Chronelec hardware.
