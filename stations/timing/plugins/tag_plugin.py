#!/usr/bin/env python3
"""
TAG Heuer timing system plugin.

Reads transponder data from serial port with frames like:
    <STA 023066 80:27'53"016 01 01 01 3 1569>

Based on read_from_loop.py
"""

import asyncio
import re
import sys
from datetime import datetime
from typing import Optional
import serial_asyncio

from .base_plugin import TimingPlugin, CrossingEvent


# Matches: <STA 023066 80:27'53"016 ...>
RE_FRAME = re.compile(rb"<STA\s+(\d+)\s+(\d+:\d+'[0-9]+\"[0-9]+).*?>")
RE_TIME = re.compile(rb"(\d+):(\d+)'(\d+)\"(\d+)")


class TagPlugin(TimingPlugin):
    """Plugin for TAG Heuer transponder timing system"""

    def __init__(self, config: dict):
        super().__init__(config)
        self.device = config.get("device", "/dev/ttyUSB0")
        self.baud = config.get("baud", 9600)
        self.parity = config.get("parity", "N")
        self.stopbits = config.get("stopbits", 1)
        self.endian = config.get("endian", "normal")

        self.reader = None
        self.writer = None
        self.read_task = None

    @staticmethod
    def bit_reverse_byte(b: int) -> int:
        """Reverse bits within a single byte, e.g. 0x23 -> 0xC4."""
        return int("{:08b}".format(b)[::-1], 2)

    def maybe_bit_reverse(self, data: bytes) -> bytes:
        """If endian == 'bitrev', reverse bits in each byte."""
        if self.endian == "bitrev":
            return bytes(self.bit_reverse_byte(b) for b in data)
        return data

    @staticmethod
    def parse_transponder_time(tbytes: bytes) -> Optional[float]:
        """
        Parse time from TAG format: 80:27'53"016
        Returns seconds as float.
        """
        m = RE_TIME.search(tbytes)
        if not m:
            return None
        h, mnt, s, ms = [int(x) for x in m.groups()]
        return h * 3600 + mnt * 60 + s + ms / 1000.0

    async def connect(self) -> bool:
        """Connect to TAG serial device"""
        try:
            self.reader, self.writer = await serial_asyncio.open_serial_connection(
                url=self.device,
                baudrate=self.baud,
                parity=self.parity,
                stopbits=self.stopbits,
            )
            self.is_connected = True
            print(
                f"TAG Plugin: Connected to {self.device} @ {self.baud} baud (endian={self.endian})"
            )
            return True
        except Exception as e:
            print(f"TAG Plugin: Failed to connect: {e}", file=sys.stderr)
            self.is_connected = False
            return False

    async def disconnect(self):
        """Disconnect from TAG device"""
        if self.is_reading:
            await self.stop_reading()

        if self.writer:
            self.writer.close()
            await self.writer.wait_closed()

        self.reader = None
        self.writer = None
        self.is_connected = False
        print("TAG Plugin: Disconnected")

    async def start_reading(self):
        """Begin reading transponder crossings"""
        if not self.is_connected:
            raise RuntimeError("Not connected to TAG device")

        if self.is_reading:
            return

        self.is_reading = True
        self.read_task = asyncio.create_task(self._read_loop())
        print("TAG Plugin: Started reading")

    async def stop_reading(self):
        """Stop reading transponder crossings"""
        if not self.is_reading:
            return

        self.is_reading = False
        if self.read_task:
            self.read_task.cancel()
            try:
                await self.read_task
            except asyncio.CancelledError:
                pass
            self.read_task = None

        print("TAG Plugin: Stopped reading")

    async def _read_loop(self):
        """Main reading loop"""
        while self.is_reading:
            try:
                raw = await self.reader.readline()
                if not raw:
                    await asyncio.sleep(0.01)
                    continue

                # Reverse bits if requested
                data = self.maybe_bit_reverse(raw.strip())

                match = RE_FRAME.search(data)
                if not match:
                    continue

                transponder_id = match.group(1).decode()
                raw_time = self.parse_transponder_time(match.group(2))
                if raw_time is None:
                    continue

                crossing = CrossingEvent(
                    transponder_id=transponder_id,
                    timestamp=datetime.now(),
                    raw_time=raw_time,
                    signal_strength=0,
                )

                # Trigger callback
                await self.on_crossing(crossing)

            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"TAG Plugin: Error in read loop: {e}", file=sys.stderr)
                await asyncio.sleep(0.1)

    def get_status(self) -> dict:
        """Return current plugin status"""
        return {
            "plugin_type": "TAG",
            "connected": self.is_connected,
            "reading": self.is_reading,
            "device": self.device,
            "baud": self.baud,
        }
