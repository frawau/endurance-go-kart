#!/usr/bin/env python3
import os
import asyncio
import mmap
import struct
import json
import logging
import argparse
import hmac
import hashlib
import time
import tomllib
from datetime import datetime
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
import aiohttp
import RPi.GPIO as GPIO
from smbus2_asyncio import SMBus2Asyncio

# Default GPIO Pin definitions (will be overridden by command line args)
DEFAULT_BUTTON_PIN = 18  # Physical pin 18 (GPIO24)
DEFAULT_SENSOR_PIN = 24  # Physical pin 24 (GPIO8)

# I2C settings
I2C_BUS = 1
RELAY_ADDRESS = 0x10  # Adjust based on your relay board

# Font sizes - doubled for better visibility
COUNTDOWN_FONT_SIZE = 400
TEAM_FONT_SIZE = 400
STATUS_FONT_SIZE = 200  # Smaller font for status messages


class I2CRelay:
    def __init__(self, bus=I2C_BUS, address=RELAY_ADDRESS):
        self.bus_num = bus
        self.address = address
        self.handle = None

    async def open(self):
        self.handle = SMBus2Asyncio(self.bus_num)
        await self.handle.open()

    async def turn_on(self):
        try:
            if self.handle is None:
                await self.open()
            await self.handle.write_byte_data(self.address, 0, 0xFF)
        except Exception as e:
            logging.error(f"I2C relay on error: {e}")

    async def turn_off(self):
        try:
            if self.handle is None:
                await self.open()
            await self.handle.write_byte_data(self.address, 0, 0x00)
        except Exception as e:
            logging.error(f"I2C relay off error: {e}")

    def close(self):
        pass


class FramebufferDisplay:
    def __init__(self):
        self.fb_device = "/dev/fb0"
        self.get_screen_info()
        self.fb_fd = os.open(self.fb_device, os.O_RDWR)
        self.fb_map = mmap.mmap(self.fb_fd, self.screen_size)

        # Load fonts
        try:
            self.countdown_font = ImageFont.truetype(
                "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
                COUNTDOWN_FONT_SIZE,
            )
            self.team_font = ImageFont.truetype(
                "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", TEAM_FONT_SIZE
            )
            self.status_font = ImageFont.truetype(
                "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", STATUS_FONT_SIZE
            )
        except:
            self.countdown_font = ImageFont.load_default()
            self.team_font = ImageFont.load_default()
            self.status_font = ImageFont.load_default()

        # Measure display performance for timing compensation
        self.display_time = self._measure_display_time()

    def get_screen_info(self):
        # Try to detect from /sys/class/graphics/fb0/virtual_size first
        try:
            with open("/sys/class/graphics/fb0/virtual_size", "r") as f:
                size_str = f.read().strip()
                width, height = map(int, size_str.split(","))
                self.width = width
                self.height = height
                logging.info(f"Detected framebuffer size: {self.width}x{self.height}")
        except Exception as e:
            logging.warning(
                f"Framebuffer size detection failed ({e}), using fallback resolution"
            )
            self.width = 1920
            self.height = 1080

        self.bpp = 32
        self.screen_size = self.width * self.height * (self.bpp // 8)

    def _measure_display_time(self):
        """Measure how long it takes to generate and display a countdown number"""
        logging.info("Measuring display performance...")

        # Test with number "20" as a representative sample
        start_time = time.perf_counter()
        self.display_text("20", (255, 165, 0), (0, 0, 0))
        end_time = time.perf_counter()

        display_time = end_time - start_time
        logging.info(f"Display time measured: {display_time:.4f} seconds")
        return display_time

    def fill_screen(self, color):
        pixel = struct.pack("BBBB", color[2], color[1], color[0], 255)
        data = pixel * (self.width * self.height)
        self.fb_map.seek(0)
        self.fb_map.write(data)
        self.fb_map.flush()

    def display_text(self, text, bg_color, text_color, font=None):
        if font is None:
            font = self.countdown_font

        img = Image.new("RGB", (self.width, self.height), bg_color)
        draw = ImageDraw.Draw(img)

        bbox = draw.textbbox((0, 0), text, font=font)
        text_width = bbox[2] - bbox[0]
        text_height = bbox[3] - bbox[1]
        x = (self.width - text_width) // 2
        y = (self.height - text_height) // 2

        draw.text((x, y), text, fill=text_color, font=font)
        self.display_image(img)

    def display_image(self, img):
        if img.size != (self.width, self.height):
            img = img.resize((self.width, self.height))

        # Convert RGB to BGRA efficiently using numpy
        try:
            import numpy as np

            # Convert PIL image to numpy array
            rgb_array = np.array(img)

            # Create BGRA array
            bgra_array = np.zeros((self.height, self.width, 4), dtype=np.uint8)
            bgra_array[:, :, 0] = rgb_array[:, :, 2]  # B
            bgra_array[:, :, 1] = rgb_array[:, :, 1]  # G
            bgra_array[:, :, 2] = rgb_array[:, :, 0]  # R
            bgra_array[:, :, 3] = 255  # A

            data = bgra_array.tobytes()

        except ImportError:
            # Fallback: use PIL's built-in conversion (slower but works)
            logging.warning("NumPy not available, using slower conversion...")

            # Convert to RGBA first, then swap channels
            if img.mode != "RGBA":
                img = img.convert("RGBA")

            # Get raw pixel data
            pixels = img.tobytes()

            # Convert RGBA to BGRA
            data = b""
            for i in range(0, len(pixels), 4):
                r, g, b, a = pixels[i : i + 4]
                data += struct.pack("BBBB", b, g, r, 255)

        self.fb_map.seek(0)
        self.fb_map.write(data)
        self.fb_map.flush()

    def display_status_text(self, text, bg_color=(0, 255, 0), text_color=(0, 0, 0)):
        """Display status message with smaller font"""
        self.display_text(text, bg_color, text_color, self.status_font)

    def close(self):
        self.fb_map.close()
        os.close(self.fb_fd)


class StopAndGoStation:
    def __init__(self, websocket_url, button_pin, sensor_pin, hmac_secret):
        self.websocket_url = websocket_url
        self.button_pin = button_pin
        self.sensor_pin = sensor_pin
        self.hmac_secret = hmac_secret.encode("utf-8")  # Convert to bytes
        self.display = FramebufferDisplay()
        self.relay = I2CRelay()
        self.current_team = None
        self.current_duration = None
        self.last_team = None  # Track team for acknowledgment handling
        self.state = "idle"  # idle, wait_countdown, countdown, breached, green, button_pressed, fence_breach
        self.countdown_task = None
        self.websocket = None
        self.penalty_ack_received = False
        self.connected = False
        self.fence_enabled = True  # Default: fence function enabled
        self.green_screen_task = None
        self.breach_state = False  # Current fence breach status
        self.penalty_ok_task = None  # Track penalty_served sending task

        # Setup GPIO
        GPIO.setmode(GPIO.BOARD)  # Use physical pin numbers
        GPIO.setup(self.button_pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)
        GPIO.setup(self.sensor_pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)

        # Initial state - show connecting
        self.display.display_status_text("Connecting", (255, 255, 0), (0, 0, 0))

    async def websocket_handler(self):
        while True:
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.ws_connect(self.websocket_url) as ws:
                        self.websocket = ws
                        self.connected = True
                        logging.info("WebSocket connected")

                        # Show race mode screen when connected
                        if self.state == "idle":
                            self.display.display_status_text("Race Mode")

                        async for msg in ws:
                            if msg.type == aiohttp.WSMsgType.TEXT:
                                try:
                                    data = json.loads(msg.data)
                                    await self.handle_message(data)
                                except json.JSONDecodeError:
                                    logging.error("Invalid JSON received")
                            elif msg.type == aiohttp.WSMsgType.ERROR:
                                logging.error(f"WebSocket error: {ws.exception()}")
                                break
            except Exception as e:
                logging.error(f"WebSocket connection failed: {e}")
                self.websocket = None
                self.connected = False

                # Show connecting screen when disconnected
                if self.state == "idle":
                    self.display.display_status_text(
                        "Connecting", (255, 255, 0), (0, 0, 0)
                    )

                await asyncio.sleep(5)  # Wait before reconnecting

    def verify_hmac(self, message_data, provided_signature):
        """Verify HMAC signature for incoming message"""
        # Create message string from data (excluding signature)
        message_str = json.dumps(message_data, sort_keys=False, separators=(",", ":"))
        expected_signature = hmac.new(
            self.hmac_secret,
            message_str.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        return hmac.compare_digest(expected_signature, provided_signature)

    def sign_message(self, message_data):
        """Sign outgoing message with HMAC"""
        message_str = json.dumps(message_data, sort_keys=False, separators=(",", ":"))
        signature = hmac.new(
            self.hmac_secret,
            message_str.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        message_data["hmac_signature"] = signature
        return message_data

    async def handle_message(self, data):
        # Verify HMAC signature for all incoming messages
        provided_signature = data.pop("hmac_signature", None)
        if not provided_signature:
            logging.warning(f"Received message without HMAC signature: {data}")
            return

        if not self.verify_hmac(data, provided_signature):
            logging.warning("HMAC verification failed - rejecting message")
            return

        logging.debug(
            f"HMAC verification successful for {data}"
        )  # Use debug to reduce log spam

        # Handle penalty acknowledgment messages (not command type)
        if data.get("type") == "penalty_acknowledged" and "team" in data:
            if data["team"] == self.last_team:
                self.penalty_ack_received = True
                logging.info(
                    f"Penalty acknowledgment received for team {self.last_team}"
                )
                # Cancel the penalty_ok sending task
                if self.penalty_ok_task and not self.penalty_ok_task.done():
                    self.penalty_ok_task.cancel()
                    self.penalty_ok_task = None
                # Reset last_team after acknowledgment
                self.last_team = None
                # Reset to idle after receiving acknowledgment
                await self.reset_to_idle()
            return

        # Only process messages marked as commands for other message types
        if data.get("type") != "command":
            return

        command = data.get("command")

        # Handle penalty required command
        if command == "penalty_required" and "team" in data and "duration" in data:
            await self.handle_penalty_command(data)

        # Handle fence enable/disable command
        elif command == "set_fence":
            self.fence_enabled = data.get("enabled", True)
            logging.info(
                f"Fence function {'enabled' if self.fence_enabled else 'disabled'}"
            )
            # Send response
            await self.send_response("fence_status", {"enabled": self.fence_enabled})

        # Handle fence status query
        elif command == "get_fence_status":
            await self.send_response("fence_status", {"enabled": self.fence_enabled})

        # Handle force penalty completion
        elif command == "force_complete":
            if (
                self.state == "green" or self.state == "breached"
            ) and self.current_team:
                logging.info(f"Force completing penalty for team {self.current_team}")
                # Send penalty served message (will set last_team)
                self.penalty_ok_task = asyncio.create_task(self.send_penalty_ok())

        # Handle reset command (clear display and return to idle)
        elif command == "reset":
            logging.info(
                "Reset command received - clearing display and returning to idle"
            )
            await self.reset_to_idle()

    async def send_response(self, response_type, data):
        """Send a response message via websocket with HMAC signature"""
        if self.websocket:
            try:
                message = {
                    "type": "response",
                    "response": response_type,
                    "timestamp": datetime.now().isoformat(),
                    **data,
                }
                # Sign the message
                signed_message = self.sign_message(message)
                await self.websocket.send_str(json.dumps(signed_message))
                logging.info(f"Sent signed response: {response_type}")
            except Exception as e:
                logging.error(f"Failed to send response: {e}")

    async def send_penalty_ok(self):
        """Send penalty ok message every 5 seconds until acknowledged"""
        # Set last_team when sending penalty served
        self.last_team = self.current_team
        while not self.penalty_ack_received:
            await self.send_response("penalty_served", {"team": self.last_team})
            await asyncio.sleep(5)

    async def handle_penalty_command(self, data):
        if "team" in data and "duration" in data:
            self.current_team = data["team"]
            self.current_duration = data["duration"]
            self.state = "wait_countdown"
            self.penalty_ack_received = False  # Reset for new race

            # Turn on relay and show team number
            await self.relay.turn_on()
            self.display.display_text(
                str(self.current_team), (255, 165, 0), (0, 0, 0), self.display.team_font
            )
            logging.info(
                f"Penalty required for team {self.current_team}, duration {self.current_duration}s"
            )

    async def button_monitor(self):
        last_button_state = False
        while True:
            current_button_state = not GPIO.input(
                self.button_pin
            )  # Inverted because pull-up

            # Detect button press (transition from not pressed to pressed)
            if current_button_state and not last_button_state:
                if self.state == "wait_countdown" or (
                    self.state == "breached" and not self.breach_state
                ):
                    # Button pressed in wait_countdown or breached with fence clear -> start countdown
                    if self.countdown_task and not self.countdown_task.done():
                        self.countdown_task.cancel()
                    self.state = "countdown"
                    await self.start_countdown()
                    if self.state == "breached":
                        logging.info(
                            "Button pressed with fence clear - restarting countdown"
                        )
                elif self.state == "countdown":
                    # Button pressed during countdown -> do nothing
                    pass
                elif self.state == "breached":
                    # Button pressed during breached state but fence still breached
                    logging.info("Button pressed but fence still breached - ignoring")
                elif self.state == "idle" and self.connected:
                    # Button pressed when no stop and go is active
                    await self.show_button_pressed()
                elif self.state == "green":
                    # Button pressed during green screen - reset to race mode immediately
                    await self.reset_to_idle()

            last_button_state = current_button_state
            await asyncio.sleep(0.1)

    async def sensor_monitor(self):
        while True:
            # Only monitor sensor if fence function is enabled
            if self.fence_enabled:
                current_breach = not GPIO.input(
                    self.sensor_pin
                )  # Inverted because pull-up

                # Update breach state when it changes
                if current_breach != self.breach_state:
                    self.breach_state = current_breach

                    if current_breach:  # Fence just got breached
                        if self.state == "wait_countdown":
                            # Go to breached state and redraw with breach colors
                            self.state = "breached"
                            self.display.display_text(
                                str(self.current_team),
                                (255, 0, 0),
                                (255, 255, 0),
                                self.display.team_font,
                            )
                            logging.info(
                                "Fence breached during wait_countdown - going to breached state"
                            )
                        elif self.state == "countdown":
                            # Go to breached state, continue countdown with different colors
                            self.state = "breached"
                            logging.info(
                                "Fence breached during countdown - going to breached state, continuing countdown"
                            )
                        elif self.state == "idle" and self.connected:
                            # Fence breached when no stop and go is active
                            await self.show_fence_breach()
                    else:  # Fence just cleared
                        if self.state == "green" and self.penalty_ack_received:
                            # Green screen and penalty acknowledged - can reset
                            await self.reset_to_idle()
            else:
                # If fence is disabled, clear breach state
                self.breach_state = False

            await asyncio.sleep(0.1)

    async def handle_sensor_triggered(self):
        if self.countdown_task:
            self.countdown_task.cancel()

        self.state = "sensor_triggered"
        self.display.display_text(
            str(self.current_team), (255, 0, 0), (255, 255, 0), self.display.team_font
        )
        logging.info("Sensor triggered - showing red screen")

    async def return_to_waiting(self):
        self.state = "waiting_button"
        self.display.display_text(
            str(self.current_team), (255, 165, 0), (0, 0, 0), self.display.team_font
        )
        logging.info("Sensor cleared - returning to orange screen")

    async def start_countdown(self):
        self.state = "countdown"
        await self.relay.turn_off()

        # Start countdown task but don't await it
        self.countdown_task = asyncio.create_task(self.countdown())

    async def countdown(self):
        for i in range(
            self.current_duration, -1, -1
        ):  # Go down to 0 instead of stopping at 1
            if self.state not in ["countdown", "breached"]:
                return

            # Display the number and measure actual time taken
            start_time = time.perf_counter()

            # Choose colors based on FSM state
            if self.state == "breached":
                # Yellow text on red background when in breached state
                bg_color = (255, 0, 0)
                text_color = (255, 255, 0)
            else:
                # Normal orange background with black text
                bg_color = (255, 165, 0)
                text_color = (0, 0, 0)

            self.display.display_text(str(i), bg_color, text_color)
            display_time = time.perf_counter() - start_time

            # Don't sleep after displaying 0
            if i > 0:
                sleep_time = max(0, 1.0 - display_time)
                await asyncio.sleep(sleep_time)

        # Countdown finished - check FSM state
        if self.state == "breached":
            # Breached countdown finished - stay on yellow 0 on red and wait
            # Keep state as "breached", display will show yellow 0 on red
            logging.info(
                "Breached countdown finished - staying in breached state, waiting for fence clear and button press"
            )
            # Don't send penalty served message, just wait
        else:
            # Normal countdown finished
            self.state = "green"
            self.display.fill_screen((0, 255, 0))  # Green screen
            logging.info("Countdown finished - showing green screen")

            # Start sending penalty ok messages
            self.penalty_ok_task = asyncio.create_task(self.send_penalty_ok())

            # Start green screen timeout (10 seconds)
            self.green_screen_task = asyncio.create_task(self.green_screen_timeout())

    async def reset_to_idle(self):
        self.state = "idle"
        self.current_team = None
        self.current_duration = None
        self.last_team = None  # Reset last_team
        self.penalty_ack_received = False  # Reset for next penalty
        await self.relay.turn_off()

        # Cancel green screen timeout if it exists
        if self.green_screen_task:
            self.green_screen_task.cancel()
            self.green_screen_task = None

        # Cancel penalty_ok task if it exists
        if self.penalty_ok_task and not self.penalty_ok_task.done():
            self.penalty_ok_task.cancel()
            self.penalty_ok_task = None

        # Cancel countdown task if it exists
        if self.countdown_task and not self.countdown_task.done():
            self.countdown_task.cancel()

        # Show appropriate idle screen based on connection status
        if self.connected:
            self.display.display_status_text("Race Mode")
        else:
            self.display.display_status_text("Connecting", (255, 255, 0), (0, 0, 0))

        logging.info("Reset to idle state")

    async def show_button_pressed(self):
        """Show 'Button Pressed' screen for 3 seconds when button pressed in idle state"""
        self.state = "button_pressed"
        self.display.display_status_text(
            "Button Pressed", (0, 0, 255), (255, 255, 255)
        )  # Blue background, white text
        logging.info("Button pressed in idle state - showing 'Button Pressed' screen")

        await asyncio.sleep(3)

        # Return to appropriate idle screen
        if self.state == "button_pressed":  # Make sure we haven't changed state
            await self.reset_to_idle()

    async def show_fence_breach(self):
        """Show 'Breach' screen for 3 seconds when fence breached in idle state"""
        self.state = "fence_breach"
        self.display.display_status_text(
            "Breach", (255, 0, 0), (255, 255, 255)
        )  # Red background, white text
        logging.info("Fence breached in idle state - showing 'Breach' screen")

        await asyncio.sleep(3)

        # Return to appropriate idle screen
        if self.state == "fence_breach":  # Make sure we haven't changed state
            await self.reset_to_idle()

    async def green_screen_timeout(self):
        """Auto-return to race mode after 10 seconds on green screen"""
        try:
            await asyncio.sleep(10)
            if self.state == "green":
                logging.info("Green screen timeout - returning to race mode")
                await self.reset_to_idle()
        except asyncio.CancelledError:
            pass

    async def run(self):
        tasks = [
            asyncio.create_task(self.websocket_handler()),
            asyncio.create_task(self.button_monitor()),
            asyncio.create_task(self.sensor_monitor()),
        ]

        try:
            await asyncio.gather(*tasks)
        except (KeyboardInterrupt, asyncio.CancelledError):
            logging.info("Received Ctrl-C, shutting down gracefully...")

            # Cancel all running tasks
            for task in tasks:
                if not task.done():
                    task.cancel()

            # Cancel countdown and green screen tasks if running
            if self.countdown_task and not self.countdown_task.done():
                self.countdown_task.cancel()
            if self.green_screen_task and not self.green_screen_task.done():
                self.green_screen_task.cancel()

            # Wait for tasks to clean up and suppress CancelledError
            try:
                await asyncio.gather(*tasks, return_exceptions=True)
            except:
                pass

        except Exception as e:
            logging.error(f"Unexpected error: {e}")
        finally:
            logging.info("Cleaning up hardware...")
            try:
                await self.relay.turn_off()
            except:
                pass
            self.display.close()
            self.relay.close()
            GPIO.cleanup()
            logging.info("Shutdown complete")


def load_config(config_path):
    """Load configuration from TOML file"""
    try:
        with open(config_path, "rb") as f:
            config = tomllib.load(f)
        logging.info(f"Loaded configuration from {config_path}")
        return config
    except FileNotFoundError:
        logging.warning(f"Config file {config_path} not found")
        return {}
    except Exception as e:
        logging.error(f"Error loading config file {config_path}: {e}")
        return {}


def parse_arguments():
    parser = argparse.ArgumentParser(
        description="Stop and Go Station for Go-Kart Racing"
    )
    parser.add_argument(
        "-c",
        "--config",
        type=str,
        help="Path to TOML configuration file",
    )
    parser.add_argument(
        "-s",
        "--server",
        help="Server hostname (default: gokart.wautier.eu)",
    )
    parser.add_argument("-p", "--port", type=int, help="Server port (default: 8000)")
    parser.add_argument(
        "-S",
        "--secure",
        action="store_true",
        help="Use secure WebSocket (wss://) instead of ws://",
    )
    parser.add_argument(
        "-b",
        "--button",
        type=int,
        help=f"Physical button pin number (default: {DEFAULT_BUTTON_PIN})",
    )
    parser.add_argument(
        "-f",
        "--fence",
        type=int,
        help=f"Physical fence sensor pin number (default: {DEFAULT_SENSOR_PIN})",
    )
    parser.add_argument(
        "-d", "--debug", action="store_true", help="Set log level to DEBUG"
    )
    parser.add_argument(
        "-i", "--info", action="store_true", help="Set log level to INFO"
    )
    parser.add_argument(
        "-H",
        "--hmac-secret",
        help="HMAC secret key for message authentication (default: race_control_hmac_key_2024)",
    )

    args = parser.parse_args()

    # Load config file if specified
    config = {}
    if args.config:
        config = load_config(args.config)

    # Set defaults - command line args override config file values
    defaults = {
        "server": "gokart.wautier.eu",
        "port": 8000,
        "secure": False,
        "button": DEFAULT_BUTTON_PIN,
        "fence": DEFAULT_SENSOR_PIN,
        "debug": False,
        "info": False,
        "hmac_secret": "race_control_hmac_key_2024",
    }

    # Apply config file values, then command line overrides
    for key, default_value in defaults.items():
        # Get value from config file first
        config_value = config.get(key, default_value)
        # Use command line argument if provided, otherwise use config/default
        cmd_value = getattr(args, key)
        if cmd_value is not None:
            setattr(args, key, cmd_value)
        else:
            setattr(args, key, config_value)

    return args


async def main():
    args = parse_arguments()

    # Set log level based on arguments
    log_level = logging.WARNING  # Default
    if args.debug:
        log_level = logging.DEBUG
    elif args.info:
        log_level = logging.INFO

    logging.basicConfig(
        level=log_level, format="%(asctime)s - %(levelname)s - %(message)s"
    )

    # Build WebSocket URL from arguments
    # Use secure WebSocket if --secure flag is provided or port is 443
    schema = "wss" if args.secure or args.port == 443 else "ws"
    websocket_url = f"{schema}://{args.server}:{args.port}/ws/stopandgo/"
    logging.info(f"Connecting to: {websocket_url}")
    logging.info(f"Button pin: {args.button}, Fence sensor pin: {args.fence}")

    station = StopAndGoStation(websocket_url, args.button, args.fence, args.hmac_secret)
    await station.run()


if __name__ == "__main__":
    asyncio.run(main())
