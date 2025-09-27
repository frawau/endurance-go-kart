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

## 🚀 Quick Start

### Prerequisites
- Python 3.8+
- Django 4.2+
- Redis (for WebSocket support)
- PostgreSQL or SQLite

### Installation

```bash
# Clone the repository
git clone https://github.com/frawau/gokartrace.git
cd gokartrace

# Create virtual environment
python -m venv env
source env/bin/activate  # On Windows: env\Scripts\activate

# Install dependencies
pip install -r requirements.txt

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
