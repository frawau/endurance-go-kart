#!/usr/bin/env python3
"""
Asset installation script for Go-Kart Race application.
Downloads and installs required flags and fonts.
"""

import argparse
import os
import sys
import urllib.request
import zipfile
import tempfile
import shutil
from pathlib import Path


def ensure_dir(path):
    """Create directory if it doesn't exist."""
    Path(path).mkdir(parents=True, exist_ok=True)


def download_file(url, destination):
    """Download a file from URL to destination."""
    print(f"Downloading {url}...")
    try:
        urllib.request.urlretrieve(url, destination)
        print(f"Downloaded to {destination}")
        return True
    except Exception as e:
        print(f"Failed to download {url}: {e}")
        return False


def download_google_fonts(font_dir="/usr/local/share/fonts"):
    """Download Google Noto fonts."""
    fonts = {
        "NotoSans-Regular.ttf": "https://github.com/googlefonts/noto-fonts/raw/main/hinted/ttf/NotoSans/NotoSans-Regular.ttf",
        "NotoSansJP-Regular.ttf": "https://github.com/notofonts/noto-cjk/raw/main/Sans/Variable/TTF/NotoSansCJKjp-VF.ttf",
        "NotoSansKR-Regular.ttf": "https://github.com/notofonts/noto-cjk/raw/main/Sans/Variable/TTF/NotoSansCJKkr-VF.ttf",
        "NotoSansTC-Regular.ttf": "https://github.com/notofonts/noto-cjk/raw/main/Sans/Variable/TTF/NotoSansCJKtc-VF.ttf",
        "NotoSansThai-Regular.ttf": "https://github.com/googlefonts/noto-fonts/raw/main/hinted/ttf/NotoSansThai/NotoSansThai-Regular.ttf",
    }

    font_dir = Path(font_dir)
    ensure_dir(font_dir)

    for font_name, url in fonts.items():
        font_path = font_dir / font_name
        if not font_path.exists():
            if download_file(url, str(font_path)):
                print(f"✓ Installed font: {font_name}")
            else:
                print(f"✗ Failed to install font: {font_name}")
        else:
            print(f"✓ Font already exists: {font_name}")


def download_country_flags(flag_dir="./static/flags"):
    """Download country flags from Flagpedia.net with fixed height."""
    import pycountry

    flag_dir = Path(flag_dir)
    ensure_dir(flag_dir)

    # Flagpedia.net CDN URL pattern for fixed height flags (h240 = 240px height, largest under 512px)
    base_url = "https://flagcdn.com/h240"

    # Get all countries from pycountry
    countries = list(pycountry.countries)

    success_count = 0
    failed_countries = []

    print(
        f"Downloading {len(countries)} country flags from Flagpedia.net (240px height)..."
    )

    for country in countries:
        country_code = country.alpha_2.lower()
        flag_url = f"{base_url}/{country_code}.png"
        flag_path = flag_dir / f"{country_code}.png"

        if not flag_path.exists():
            if download_file(flag_url, str(flag_path)):
                success_count += 1
                print(f"✓ Downloaded flag: {country_code}.png ({country.name})")
            else:
                failed_countries.append(f"{country_code} ({country.name})")
        else:
            success_count += 1
            print(f"✓ Flag already exists: {country_code}.png")

    # Download UN flag as fallback
    un_flag_url = f"{base_url}/un.png"
    un_flag_path = flag_dir / "un.png"
    if not un_flag_path.exists():
        if download_file(un_flag_url, str(un_flag_path)):
            success_count += 1
            print("✓ Downloaded UN flag")
        else:
            print("✗ Failed to download UN flag")

    print(f"\n✓ Successfully installed {success_count} country flags")

    if failed_countries:
        print(f"✗ Failed to download {len(failed_countries)} flags:")
        for country in failed_countries[:10]:  # Show only first 10 failures
            print(f"  - {country}")
        if len(failed_countries) > 10:
            print(f"  ... and {len(failed_countries) - 10} more")


def create_fallback_flags(flag_dir="./static/flags"):
    """Create simple fallback flags if downloads fail."""
    flag_dir = Path(flag_dir)
    ensure_dir(flag_dir)

    # Create a simple UN flag as fallback (solid blue with UN logo placeholder)
    un_flag = flag_dir / "un.png"
    if not un_flag.exists():
        print("Creating fallback UN flag...")
        # In a real scenario, you'd create a simple colored PNG here
        # For now, just create an empty file as placeholder
        un_flag.touch()


def parse_arguments():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Install assets (fonts and flags) for Go-Kart Race application",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python3 install_assets.py                          # Install both fonts and flags
  python3 install_assets.py -n                       # Install flags only
  python3 install_assets.py -N                       # Install fonts only
  python3 install_assets.py --fonts-dir ./fonts      # Custom font directory
  python3 install_assets.py --flags-dir ./assets     # Custom flag directory
        """,
    )

    parser.add_argument(
        "-n", "--no-fonts", action="store_true", help="Skip font installation"
    )

    parser.add_argument(
        "-N", "--no-flags", action="store_true", help="Skip flag installation"
    )

    parser.add_argument(
        "--fonts-dir",
        default="/usr/local/share/fonts",
        help="Directory to install fonts (default: /usr/local/share/fonts)",
    )

    parser.add_argument(
        "--flags-dir",
        default="./static/flags",
        help="Directory to install flags (default: ./static/flags)",
    )

    return parser.parse_args()


def main():
    """Main installation function."""
    args = parse_arguments()

    print("Go-Kart Race Asset Installation")
    print("=" * 40)

    # Validate arguments
    if args.no_fonts and args.no_flags:
        print("Error: Cannot skip both fonts and flags. Nothing to install.")
        sys.exit(1)

    # Font installation
    if not args.no_fonts:
        # Check if running as root for font installation
        if os.geteuid() != 0:
            print("Warning: Not running as root. Font installation may fail.")
            print("Consider running: sudo python3 install_assets.py")

        print(f"\n1. Installing fonts to {args.fonts_dir}...")
        try:
            download_google_fonts(args.fonts_dir)
        except Exception as e:
            print(f"Font installation failed: {e}")

        print("\n   Updating font cache...")
        try:
            # Update font cache
            os.system("fc-cache -fv")
            print("✓ Font cache updated")
        except Exception as e:
            print(f"Font cache update failed: {e}")
    else:
        print("\n1. Skipping font installation (-n/--no-fonts)")

    # Flag installation
    if not args.no_flags:
        print(f"\n2. Installing country flags to {args.flags_dir}...")
        try:
            download_country_flags(args.flags_dir)
            create_fallback_flags(args.flags_dir)
        except Exception as e:
            print(f"Flag installation failed: {e}")
    else:
        print("\n2. Skipping flag installation (-N/--no-flags)")

    print("\nInstallation complete!")

    if not args.no_fonts or not args.no_flags:
        print("\nNext steps:")
        if not args.no_fonts:
            print("1. Verify fonts are accessible in your application")
        if not args.no_flags:
            print("2. Ensure static files are properly configured")
            print("3. Test flag display in templates")


if __name__ == "__main__":
    main()
