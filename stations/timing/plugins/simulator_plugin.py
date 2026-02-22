#!/usr/bin/env python3
"""
Simulator plugin for testing timing system without hardware.

Simulates transponder crossings at realistic intervals.
Supports all four timing modes: interval, duration, time_of_day, own_time.
"""

import asyncio
import random
from datetime import datetime
from typing import List

from .base_plugin import TimingPlugin, CrossingEvent


class SimulatorPlugin(TimingPlugin):
    """Plugin that simulates transponder crossings for testing"""

    def __init__(
        self,
        config: dict,
        *,
        timing_mode: str = "duration",
        rollover_seconds: float = 360000.0,
    ):
        super().__init__(config)
        self.num_transponders = config.get("num_transponders", 10)
        self.lap_time_min = config.get("lap_time_min", 45.0)  # seconds
        self.lap_time_max = config.get("lap_time_max", 75.0)  # seconds
        self.lap_time_variance = config.get("lap_time_variance", 5.0)  # seconds
        # Optional: fixed transponder ID list (overrides auto-generated IDs)
        self._fixed_transponder_ids: list = config.get("transponder_ids", [])
        # Simulation speed: 1.0 = real-time, 10.0 = 10x faster (default)
        self.sim_speed: float = float(config.get("sim_speed", 10.0))

        self.timing_mode = timing_mode
        self.rollover_seconds = rollover_seconds

        self.simulate_task = None
        self.transponder_ids = []
        # id -> (cumulative_time, base_lap_time, last_lap_time)
        self.transponder_states = {}
        self.race_start_time = 0.0
        # For time_of_day mode: seconds-since-midnight at simulated start
        self._tod_offset = 0.0

    async def connect(self) -> bool:
        """Simulate connection"""
        # Use fixed IDs from config if provided, otherwise auto-generate
        if self._fixed_transponder_ids:
            self.transponder_ids = list(self._fixed_transponder_ids)
        else:
            self.transponder_ids = [
                f"{100000 + i:06d}" for i in range(self.num_transponders)
            ]

        # Initialize each transponder with a base lap time
        for tid in self.transponder_ids:
            base_lap_time = random.uniform(self.lap_time_min, self.lap_time_max)
            self.transponder_states[tid] = (0.0, base_lap_time, 0.0)

        # For time_of_day: use current wall-clock seconds-since-midnight
        now = datetime.now()
        self._tod_offset = now.hour * 3600 + now.minute * 60 + now.second

        self.is_connected = True
        print(
            f"Simulator Plugin: Connected with {self.num_transponders} transponders "
            f"(timing_mode={self.timing_mode})"
        )
        return True

    async def disconnect(self):
        """Disconnect simulator"""
        if self.is_reading:
            await self.stop_reading()

        self.transponder_ids = []
        self.transponder_states = {}
        self.is_connected = False
        print("Simulator Plugin: Disconnected")

    async def start_reading(self):
        """Begin simulating crossings"""
        if not self.is_connected:
            raise RuntimeError("Not connected")

        if self.is_reading:
            return

        self.is_reading = True
        self.race_start_time = 0.0
        self.simulate_task = asyncio.create_task(self._simulate_race())
        print("Simulator Plugin: Started simulating")

    async def stop_reading(self):
        """Stop simulating"""
        if not self.is_reading:
            return

        self.is_reading = False
        if self.simulate_task:
            self.simulate_task.cancel()
            try:
                await self.simulate_task
            except asyncio.CancelledError:
                pass
            self.simulate_task = None

        print("Simulator Plugin: Stopped simulating")

    def _compute_raw_time(self, cumulative: float, lap_time: float) -> float:
        """Convert cumulative race time to raw_time based on timing_mode."""
        if self.timing_mode == "interval":
            # raw_time = this lap's duration (0 for first passage)
            return lap_time
        elif self.timing_mode == "duration":
            # raw_time = cumulative seconds from race start
            return cumulative
        elif self.timing_mode == "time_of_day":
            # raw_time = seconds since midnight (wrap at 86400)
            return (self._tod_offset + cumulative) % 86400.0
        elif self.timing_mode == "own_time":
            # raw_time = cumulative modulo rollover
            return cumulative % self.rollover_seconds
        else:
            return cumulative

    async def _simulate_race(self):
        """Main simulation loop"""
        # Simulate rolling start - karts cross line at different times
        start_offsets = sorted([random.uniform(0, 10) for _ in self.transponder_ids])

        for tid, offset in zip(self.transponder_ids, start_offsets):
            _cum, base_lap_time, _last = self.transponder_states[tid]
            self.transponder_states[tid] = (offset, base_lap_time, 0.0)

        while self.is_reading:
            try:
                # Find next crossing
                next_crossing_time = float("inf")
                next_tid = None
                next_variance = 0.0

                for tid in self.transponder_ids:
                    cumulative, base_lap_time, _last = self.transponder_states[tid]
                    variance = random.uniform(
                        -self.lap_time_variance, self.lap_time_variance
                    )
                    next_time = cumulative + base_lap_time + variance

                    if next_time < next_crossing_time:
                        next_crossing_time = next_time
                        next_tid = tid
                        next_variance = variance

                if next_tid is None:
                    break

                # Wait until next crossing
                current_time = self.race_start_time
                wait_time = next_crossing_time - current_time
                if wait_time > 0:
                    await asyncio.sleep(wait_time / self.sim_speed)

                self.race_start_time = next_crossing_time

                # Update state
                old_cumulative, base_lap_time, _last = self.transponder_states[next_tid]
                this_lap_time = next_crossing_time - old_cumulative
                self.transponder_states[next_tid] = (
                    next_crossing_time,
                    base_lap_time,
                    this_lap_time,
                )

                raw_time = self._compute_raw_time(next_crossing_time, this_lap_time)

                # Create crossing event
                crossing = CrossingEvent(
                    transponder_id=next_tid,
                    timestamp=datetime.now(),
                    raw_time=raw_time,
                    signal_strength=random.randint(80, 100),
                )

                # Trigger callback
                await self.on_crossing(crossing)

            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"Simulator Plugin: Error: {e}")
                await asyncio.sleep(0.1)

    def get_status(self) -> dict:
        """Return current plugin status"""
        return {
            "plugin_type": "Simulator",
            "connected": self.is_connected,
            "reading": self.is_reading,
            "num_transponders": self.num_transponders,
            "race_time": self.race_start_time,
            "timing_mode": self.timing_mode,
        }
