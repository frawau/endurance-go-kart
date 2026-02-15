#!/usr/bin/env python3
"""
TAG Heuer network timing system plugin.

Reads transponder data over UDP or TCP from Chronelec decoder.
Frames: <STA 023066 80:27'53"016 01 01 01 3 1569>

ACK flow: The decoder resends data until ACK'd. We ACK immediately
upon receiving valid data, then forward to Django. If the WebSocket
to Django fails after ACK, the next crossing will have an unusually
long lap time which Django detects as suspicious and allows splitting.
"""

import asyncio
import re
import sys
from datetime import datetime
from typing import Optional

from .base_plugin import TimingPlugin, CrossingEvent


RE_FRAME = re.compile(rb"<STA\s+(\d+)\s+(\d+:\d+'[0-9]+\"[0-9]+).*?>")
RE_TIME = re.compile(rb"(\d+):(\d+)'(\d+)\"(\d+)")

ACK_BYTES = b"\x1b\x11"


class NetTagPlugin(TimingPlugin):
    """Plugin for TAG Heuer transponder timing via network (UDP/TCP)"""

    def __init__(self, config: dict):
        super().__init__(config)
        self.host = config.get("host", "192.168.0.11")
        self.port = config.get("port", 2009)
        self.protocol = config.get("protocol", "udp").lower()

        self.transport = None
        self.protocol_obj = None
        self.reader = None
        self.writer = None
        self.read_task = None

    @staticmethod
    def parse_transponder_time(tbytes: bytes) -> Optional[float]:
        """Parse time from TAG format: 80:27'53"016 -> seconds."""
        m = RE_TIME.search(tbytes)
        if not m:
            return None
        h, mnt, s, ms = [int(x) for x in m.groups()]
        return h * 3600 + mnt * 60 + s + ms / 1000.0

    async def connect(self) -> bool:
        """Connect to TAG network device"""
        try:
            if self.protocol == "tcp":
                self.reader, self.writer = await asyncio.open_connection(
                    self.host, self.port
                )
            else:
                loop = asyncio.get_event_loop()

                class UDPProtocol(asyncio.DatagramProtocol):
                    def __init__(self):
                        self.queue = asyncio.Queue()

                    def datagram_received(self, data, addr):
                        self.queue.put_nowait((data, addr))

                transport, protocol = await loop.create_datagram_endpoint(
                    UDPProtocol,
                    local_addr=("0.0.0.0", self.port),
                )
                self.transport = transport
                self.protocol_obj = protocol

            self.is_connected = True
            print(
                f"NetTag Plugin: Connected via {self.protocol.upper()} to {self.host}:{self.port}"
            )
            return True

        except Exception as e:
            print(f"NetTag Plugin: Failed to connect: {e}", file=sys.stderr)
            self.is_connected = False
            return False

    async def disconnect(self):
        """Disconnect from TAG device"""
        if self.is_reading:
            await self.stop_reading()

        if self.protocol == "tcp":
            if self.writer:
                self.writer.close()
                await self.writer.wait_closed()
            self.reader = None
            self.writer = None
        else:
            if self.transport:
                self.transport.close()
            self.transport = None
            self.protocol_obj = None

        self.is_connected = False
        print("NetTag Plugin: Disconnected")

    async def start_reading(self):
        """Begin reading transponder crossings"""
        if not self.is_connected:
            raise RuntimeError("Not connected to NetTag device")

        if self.is_reading:
            return

        self.is_reading = True
        self.read_task = asyncio.create_task(self._read_loop())
        print("NetTag Plugin: Started reading")

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

        print("NetTag Plugin: Stopped reading")

    async def _read_loop(self):
        """Main reading loop"""
        while self.is_reading:
            try:
                if self.protocol == "tcp":
                    data = await self.reader.readline()
                    if not data:
                        await asyncio.sleep(0.01)
                        continue
                    addr = (self.host, self.port)
                else:
                    try:
                        data, addr = await asyncio.wait_for(
                            self.protocol_obj.queue.get(), timeout=1.0
                        )
                    except asyncio.TimeoutError:
                        continue

                if not data.startswith(b"<"):
                    continue

                match = RE_FRAME.search(data)
                if not match:
                    continue

                transponder_id = match.group(1).decode()
                raw_time = self.parse_transponder_time(match.group(2))
                if raw_time is None:
                    continue

                # ACK immediately so decoder moves to next reading
                try:
                    if self.protocol == "tcp":
                        self.writer.write(ACK_BYTES)
                        await self.writer.drain()
                    else:
                        self.transport.sendto(ACK_BYTES, addr)
                except Exception as e:
                    print(f"NetTag Plugin: Failed to send ACK: {e}", file=sys.stderr)

                crossing = CrossingEvent(
                    transponder_id=transponder_id,
                    timestamp=datetime.now(),
                    raw_time=raw_time,
                    signal_strength=0,
                )

                await self.on_crossing(crossing)

            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"NetTag Plugin: Error in read loop: {e}", file=sys.stderr)
                await asyncio.sleep(0.1)

    def get_status(self) -> dict:
        """Return current plugin status"""
        return {
            "plugin_type": "NetTag",
            "connected": self.is_connected,
            "reading": self.is_reading,
            "host": self.host,
            "port": self.port,
            "protocol": self.protocol,
        }
