# Asset Installation Guide

This guide explains how to install the required fonts and country flags for the Go-Kart Race application.

## Required Assets

### Fonts
The application requires the following [Google Noto Fonts](https://fonts.google.com/noto) for PDF generation:
- **NotoSans-Regular.ttf** (Latin/English text)
- **NotoSansJP-Regular.ttf** (Japanese text)
- **NotoSansKR-Regular.ttf** (Korean text)
- **NotoSansTC-Regular.ttf** (Traditional Chinese text)
- **NotoSansThai-Regular.ttf** (Thai text)

Source: [Google Fonts - Noto](https://fonts.google.com/noto) | [GitHub Repository](https://github.com/googlefonts/noto-fonts)

### Country Flags
PNG format flags from [Flagpedia.net](https://flagpedia.net) with the following specifications:
- Fixed height: 240px (maintains proper aspect ratios)
- Named with ISO 3166-1 alpha-2 country codes (lowercase)
- Examples: `ch.png` (Switzerland), `be.png` (Belgium), `hu.png` (Hungary)
- Fallback flag: `un.png` (UN flag for unknown countries)
- CDN Source: https://flagcdn.com/h240/{country_code}.png

Source: [Flagpedia.net](https://flagpedia.net) | [API Documentation](https://flagpedia.net/download/api)

## Installation Methods

### Method 1: Using the Installation Script

Run the provided installation script with various options:

```bash
# Install both fonts and flags (requires sudo for fonts)
sudo python3 install_assets.py

# Install flags only (no sudo needed)
python3 install_assets.py -n

# Install fonts only
sudo python3 install_assets.py -N

# Custom directories
python3 install_assets.py --flags-dir ./assets/flags
sudo python3 install_assets.py --fonts-dir ./local-fonts

# View all options
python3 install_assets.py --help
```

#### Command Line Options:
- `-n, --no-fonts`: Skip font installation
- `-N, --no-flags`: Skip flag installation
- `--fonts-dir DIR`: Custom font directory (default: /usr/local/share/fonts)
- `--flags-dir DIR`: Custom flag directory (default: ./static/flags)

### Method 2: Docker Build

The Dockerfile automatically installs all required assets during build:

```bash
# Build with assets
docker-compose build

# Development with volume mounts
docker-compose -f docker-compose.yml -f docker-compose.dev.yml up
```

### Method 3: Manual Installation

#### Fonts
```bash
# Install Noto fonts via package manager
sudo apt-get update
sudo apt-get install fonts-noto fonts-noto-cjk fonts-noto-cjk-extra

# Or download manually to /usr/local/share/fonts/
sudo mkdir -p /usr/local/share/fonts
# Download each font file and update font cache
sudo fc-cache -fv
```

#### Flags
```bash
# Create flags directory
mkdir -p static/flags

# Download country flags from Flagpedia.net (240px height)
# This is done automatically by the install_assets.py script
# Manual example for Switzerland:
wget https://flagcdn.com/h240/ch.png -O static/flags/ch.png
```

## Configuration

### File Paths
The application looks for assets in these locations:

- **Flags**: `static/flags/` directory (configurable via Django settings)
- **Fonts**: `/usr/local/share/fonts/` directory
- **Logo**: `static/logos/gokartrace-logo.jpg`

### PDF Card Generation
The `race/pdfcardview.py:25-26` defines the asset paths:
- `FLAGDIR`: Path to flag PNG files
- `LOGOIMG`: Path to application logo

### Web Templates
Templates use flags at:
- `templates/pages/alldriver.html:71`: `/static/flags/{country_code}.png`
- `templates/pages/edit_driver.html:139`: `/static/flags/{country_code}.png`

## Troubleshooting

### Missing Flags
- Check if flag files exist in the correct directory
- Ensure filenames match ISO 3166-1 alpha-2 codes (lowercase)
- Create fallback `un.png` for unknown countries

### Font Issues
- Verify fonts are installed: `fc-list | grep Noto`
- Update font cache: `sudo fc-cache -fv`
- Check file permissions in `/usr/local/share/fonts/`

### Docker Issues
- Ensure installation script runs during build
- Check volume mounts for development
- Verify static file collection

## Development

For development, you can:

1. Use the development Docker Compose override
2. Mount local static directories as volumes
3. Install assets locally for testing

```bash
# Development setup
docker-compose -f docker-compose.yml -f docker-compose.dev.yml up --build
```