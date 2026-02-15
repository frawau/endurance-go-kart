#!/usr/bin/env python3
"""
Timing Station - Transponder timing system daemon.

Connects to timing hardware via plugins and relays raw crossing
events to Django app via WebSocket using HMAC-signed messages.

The station is intentionally "dumb" - it only sends what it receives
from the decoder (transponder_id, timestamp, raw_time). Django handles
all the race/team/kart lookups and lap time calculation.

Architecture:
  - Plugin reads from decoder independently of WebSocket state.
  - Every crossing is buffered to SQLite before sending.
  - Django sends an ACK per message_id after processing.
  - On reconnect, all un-ACK'd crossings are replayed.

Usage:
    python timing-station.py -c timing-station.toml
"""

import argparse
import asyncio
import hashlib
import hmac
import json
import logging
import signal
import sys
from datetime import datetime

try:
    import tomllib
except ImportError:
    try:
        import toml as tomllib
    except ImportError:
        print("Error: toml package not installed. Run: pip install toml")
        sys.exit(1)

try:
    import websockets
except ImportError:
    print("Error: websockets package not installed. Run: pip install websockets")
    sys.exit(1)

# Import plugins
from plugins.base_plugin import TimingPlugin, CrossingEvent
from plugins.tag_plugin import TagPlugin
from plugins.nettag_plugin import NetTagPlugin
from plugins.simulator_plugin import SimulatorPlugin

from buffer import CrossingBuffer


class TimingStation:
    """Main timing station daemon"""

    def __init__(self, config_path: str):
        self.config = self.load_config(config_path)
        self.setup_logging()

        self.plugin = None
        self.websocket = None
        self.hmac_secret = self.config["daemon"]["hmac_secret"].encode("utf-8")
        self.websocket_url = self.config["daemon"]["websocket_url"]
        self.reconnect_interval = self.config["daemon"].get("reconnect_interval", 5.0)
        self.running = False

        # Timing mode config
        self.timing_mode = self.config["daemon"].get("timing_mode", "duration")
        self.rollover_seconds = self.config["daemon"].get("rollover_seconds", 360000.0)

        # Buffer config
        buffer_db = self.config["daemon"].get("buffer_db", "crossing_buffer.db")
        self.buffer = CrossingBuffer(buffer_db)
        self.buffer_cleanup_interval = self.config["daemon"].get(
            "buffer_cleanup_interval", 300
        )
        self.buffer_max_acked_age = self.config["daemon"].get(
            "buffer_max_acked_age", 3600
        )

    def load_config(self, config_path: str) -> dict:
        """Load configuration from TOML file"""
        try:
            with open(config_path, "rb") as f:
                return tomllib.load(f)
        except Exception as e:
            print(f"Error loading config: {e}")
            sys.exit(1)

    def setup_logging(self):
        """Setup logging"""
        log_config = self.config.get("logging", {})
        level_name = log_config.get("level", "INFO")
        log_file = log_config.get("file", "timing-station.log")

        level = getattr(logging, level_name, logging.INFO)
        logging.basicConfig(
            level=level,
            format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
            handlers=[logging.FileHandler(log_file), logging.StreamHandler()],
        )
        self.logger = logging.getLogger("TimingStation")

    def load_plugin(self) -> TimingPlugin:
        """Load the configured timing plugin"""
        plugin_type = self.config["plugin"]["type"]
        plugin_config = self.config["plugin"].get(plugin_type, {})

        if plugin_type == "tag":
            plugin = TagPlugin(plugin_config)
        elif plugin_type == "nettag":
            plugin = NetTagPlugin(plugin_config)
        elif plugin_type == "simulator":
            plugin = SimulatorPlugin(
                plugin_config,
                timing_mode=self.timing_mode,
                rollover_seconds=self.rollover_seconds,
            )
        else:
            raise ValueError(f"Unknown plugin type: {plugin_type}")

        # Override on_crossing callback
        original_on_crossing = plugin.on_crossing

        async def crossing_handler(crossing: CrossingEvent):
            await original_on_crossing(crossing)
            await self.handle_crossing(crossing)

        plugin.on_crossing = crossing_handler

        self.logger.info(f"Loaded plugin: {plugin_type}")
        return plugin

    def sign_message(self, message_data: dict) -> dict:
        """Sign outgoing message with HMAC"""
        message_str = json.dumps(message_data, sort_keys=False, separators=(",", ":"))
        signature = hmac.new(
            self.hmac_secret, message_str.encode("utf-8"), hashlib.sha256
        ).hexdigest()
        message_data["hmac_signature"] = signature
        return message_data

    def verify_hmac(self, message_data: dict, provided_signature: str) -> bool:
        """Verify HMAC signature for incoming message"""
        message_str = json.dumps(message_data, sort_keys=False, separators=(",", ":"))
        expected_signature = hmac.new(
            self.hmac_secret, message_str.encode("utf-8"), hashlib.sha256
        ).hexdigest()
        return hmac.compare_digest(expected_signature, provided_signature)

    async def handle_crossing(self, crossing: CrossingEvent):
        """
        Buffer crossing to disk, then attempt to send over WebSocket.

        The crossing is persisted *before* any network I/O so it will
        survive crashes and reconnects.
        """
        payload = {
            "type": "lap_crossing",
            "transponder_id": crossing.transponder_id,
            "timestamp": crossing.timestamp.isoformat(),
            "raw_time": crossing.raw_time,
            "signal_strength": crossing.signal_strength,
        }

        # 1. Buffer to disk (returns a unique message_id)
        message_id = self.buffer.store(payload)

        # 2. Attach message_id and try to send
        payload["message_id"] = message_id
        await self.send_message(payload)

        self.logger.info(
            f"Crossing: transponder {crossing.transponder_id} "
            f"raw_time={crossing.raw_time:.3f}s  mid={message_id[:8]}"
        )

    async def send_message(self, message: dict):
        """Send signed message to Django via WebSocket"""
        if not self.websocket:
            self.logger.debug("No WebSocket connection, message buffered only")
            return

        try:
            signed_message = self.sign_message(message.copy())
            await self.websocket.send(json.dumps(signed_message))
        except Exception as e:
            self.logger.error(f"Error sending message: {e}")

    async def handle_ack(self, message_id: str):
        """Mark a buffered crossing as acknowledged by Django."""
        if self.buffer.ack(message_id):
            self.logger.debug(f"ACK received: {message_id[:8]}")
        else:
            self.logger.warning(f"ACK for unknown message_id: {message_id[:8]}")

    async def replay_unacked(self):
        """Replay all un-ACK'd crossings to Django after reconnect."""
        unacked = self.buffer.get_unacked()
        if not unacked:
            return

        self.logger.info(f"Replaying {len(unacked)} un-ACK'd crossings")
        for message_id, payload in unacked:
            payload["message_id"] = message_id
            await self.send_message(payload)
            # Small delay to avoid flooding
            await asyncio.sleep(0.01)

    async def handle_command(self, command: dict):
        """Handle commands from Django"""
        try:
            cmd_type = command.get("command")

            if cmd_type == "get_status":
                status = self.plugin.get_status() if self.plugin else {}
                status["buffer"] = self.buffer.stats()
                await self.send_message(
                    {
                        "type": "response",
                        "response": "status",
                        "status": status,
                    }
                )

            else:
                self.logger.warning(f"Unknown command: {cmd_type}")

        except Exception as e:
            self.logger.error(f"Error handling command: {e}")

    async def buffer_cleanup_loop(self):
        """Periodically purge old ACK'd buffer entries."""
        while self.running:
            try:
                await asyncio.sleep(self.buffer_cleanup_interval)
                self.buffer.cleanup(self.buffer_max_acked_age)
            except asyncio.CancelledError:
                break
            except Exception as e:
                self.logger.error(f"Buffer cleanup error: {e}")

    async def websocket_handler(self):
        """Maintain WebSocket connection to Django app"""
        while self.running:
            try:
                self.logger.info(f"Connecting to {self.websocket_url}")
                async with websockets.connect(self.websocket_url) as websocket:
                    self.websocket = websocket
                    self.logger.info("WebSocket connected")

                    # Send connection message with timing config
                    await self.send_message(
                        {
                            "type": "connected",
                            "plugin_type": self.config["plugin"]["type"],
                            "timing_mode": self.timing_mode,
                            "rollover_seconds": self.rollover_seconds,
                            "timestamp": datetime.now().isoformat(),
                        }
                    )

                    # Replay any un-ACK'd crossings from previous session
                    await self.replay_unacked()

                    # Receive messages
                    async for message in websocket:
                        try:
                            data = json.loads(message)

                            # Verify HMAC signature
                            provided_signature = data.pop("hmac_signature", None)
                            if not provided_signature:
                                self.logger.warning(
                                    "Received message without HMAC signature"
                                )
                                continue

                            if not self.verify_hmac(data, provided_signature):
                                self.logger.warning("HMAC verification failed")
                                continue

                            msg_type = data.get("type")

                            if msg_type == "command":
                                await self.handle_command(data)
                            elif msg_type == "ack":
                                mid = data.get("message_id")
                                if mid:
                                    await self.handle_ack(mid)

                        except json.JSONDecodeError:
                            self.logger.error(f"Invalid JSON: {message}")
                        except Exception as e:
                            self.logger.error(f"Error processing message: {e}")

            except websockets.exceptions.WebSocketException as e:
                self.logger.error(f"WebSocket error: {e}")
            except Exception as e:
                self.logger.error(f"Connection error: {e}")

            self.websocket = None

            if self.running:
                self.logger.info(
                    f"Reconnecting in {self.reconnect_interval} seconds..."
                )
                await asyncio.sleep(self.reconnect_interval)

    async def start(self):
        """Start the timing station"""
        self.running = True
        self.logger.info(f"Starting timing station  timing_mode={self.timing_mode}")

        # Load and connect plugin
        self.plugin = self.load_plugin()
        connected = await self.plugin.connect()
        if not connected:
            self.logger.error("Failed to connect to timing hardware")
            return

        # Start reading from hardware immediately (independent of WebSocket)
        await self.plugin.start_reading()
        self.logger.info("Plugin reading started (independent of WebSocket)")

        # Run WebSocket handler and buffer cleanup concurrently
        cleanup_task = asyncio.create_task(self.buffer_cleanup_loop())
        try:
            await self.websocket_handler()
        finally:
            cleanup_task.cancel()
            try:
                await cleanup_task
            except asyncio.CancelledError:
                pass

    async def stop(self):
        """Stop the timing station"""
        self.logger.info("Stopping timing station")
        self.running = False

        if self.plugin:
            if self.plugin.is_reading:
                await self.plugin.stop_reading()
            await self.plugin.disconnect()

        if self.websocket:
            await self.websocket.close()

        self.buffer.close()


async def main():
    parser = argparse.ArgumentParser(description="Timing station daemon")
    parser.add_argument(
        "-c",
        "--config",
        default="timing-station.toml",
        help="Path to configuration file",
    )
    args = parser.parse_args()

    station = TimingStation(args.config)

    # Setup signal handlers
    loop = asyncio.get_event_loop()

    def signal_handler():
        print("\nShutting down...")
        asyncio.create_task(station.stop())

    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, signal_handler)

    try:
        await station.start()
    except KeyboardInterrupt:
        await station.stop()


if __name__ == "__main__":
    asyncio.run(main())
