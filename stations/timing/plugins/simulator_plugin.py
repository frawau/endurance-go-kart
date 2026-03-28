#!/usr/bin/env python3
"""
Simulator plugin for testing the timing system without hardware.

Behaviour
---------
* On connect(): POST to Django's /api/timing/sim-transponders/ to ensure
  at least `num_transponders` Transponder rows exist.  Falls back to
  auto-generated IDs if Django is unreachable.
* Stays idle after start_reading() until Django signals race_started.
* on_race_started(): assigns each active transponder a *delta* drawn from
  an exponential distribution shifted to [2, 6] seconds.  Deltas are
  stable across races in the same Round (same round_id → same deltas).
* First crossing per transponder: 1–6 s after race start, roughly in grid
  order (Le Mans variability modelled with Gaussian noise).
* Continuous laps: Gaussian around (min_time + delta), std = lap_sigma,
  floor = min_time.  Time resolution: milliseconds.
* Miss probability: each potential crossing has a `miss_probability` chance
  of not being reported.  For interval mode the unreported time accumulates
  and is delivered with the next reported crossing.
* on_race_ended(): simulation continues for `post_race_duration` more
  seconds, then idles until the next race_started signal.
"""

import asyncio
import json
import random
import urllib.request
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from .base_plugin import CrossingEvent, TimingPlugin


class SimulatorPlugin(TimingPlugin):
    """Plugin that simulates transponder crossings for testing."""

    def __init__(
        self,
        config: dict,
        *,
        timing_mode: str = "duration",
        rollover_seconds: float = 360000.0,
        app_url: Optional[str] = None,
    ):
        super().__init__(config)

        # Config
        self.num_transponders: int = config.get("num_transponders", 30)
        self.min_time: float = float(config.get("min_time", 45.0))
        self.lap_sigma: float = float(config.get("lap_sigma", 0.5))
        self.miss_probability: float = float(config.get("miss_probability", 1 / 20000))
        self.post_race_duration: float = float(config.get("post_race_duration", 120.0))
        self.app_url: Optional[str] = app_url

        self.timing_mode = timing_mode
        self.rollover_seconds = rollover_seconds

        # Transponder pool (all IDs known to this station)
        self._transponder_pool: List[str] = []

        # round_id → {transponder_id: delta_seconds}
        # Deltas are generated once per round and reused across races in that round.
        self._round_deltas: Dict[int, Dict[str, float]] = {}

        # Active race state
        self._race_id: Optional[int] = None
        self._round_id: Optional[int] = None
        # transponder_id → (first_offset_s, delta_s)
        self._current_assignments: Dict[str, Tuple[float, float]] = {}
        self._tod_offset: float = 0.0

        # Asyncio coordination
        self._race_start_event: asyncio.Event = asyncio.Event()
        self._race_end_event: asyncio.Event = asyncio.Event()
        self._sim_tasks: List[asyncio.Task] = []
        self._main_task: Optional[asyncio.Task] = None

    # ── Plugin lifecycle ──────────────────────────────────────────────────────

    async def connect(self) -> bool:
        if self.app_url:
            try:
                loop = asyncio.get_running_loop()
                url = f"{self.app_url}/api/timing/sim-transponders/"
                result = await loop.run_in_executor(
                    None,
                    self._http_post,
                    url,
                    {"ensure_count": self.num_transponders},
                )
                self._transponder_pool = result.get("transponder_ids", [])
                print(
                    f"Simulator: {len(self._transponder_pool)} transponders "
                    f"from Django ({self.app_url})"
                )
            except Exception as exc:
                print(
                    f"Simulator: could not reach Django ({exc}), "
                    f"falling back to auto-generated IDs"
                )

        if not self._transponder_pool:
            self._transponder_pool = [
                f"SIM{i + 1:06d}" for i in range(self.num_transponders)
            ]
            print(
                f"Simulator: using {len(self._transponder_pool)} "
                f"auto-generated transponder IDs"
            )

        self.is_connected = True
        print(
            f"Simulator Plugin: connected (timing_mode={self.timing_mode}), "
            f"idle — waiting for race_started signal"
        )
        return True

    async def disconnect(self):
        if self.is_reading:
            await self.stop_reading()
        self._transponder_pool = []
        self._current_assignments = {}
        self.is_connected = False
        print("Simulator Plugin: disconnected")

    async def start_reading(self):
        if not self.is_connected:
            raise RuntimeError("Not connected")
        if self.is_reading:
            return
        self.is_reading = True
        self._main_task = asyncio.create_task(self._race_loop())
        print("Simulator Plugin: started — idle until race_started")

    async def stop_reading(self):
        if not self.is_reading:
            return
        self.is_reading = False

        for task in self._sim_tasks:
            task.cancel()
        if self._sim_tasks:
            await asyncio.gather(*self._sim_tasks, return_exceptions=True)
        self._sim_tasks = []

        # Unblock the main loop if it is waiting
        self._race_start_event.set()
        self._race_end_event.set()

        if self._main_task:
            self._main_task.cancel()
            try:
                await self._main_task
            except asyncio.CancelledError:
                pass
            self._main_task = None

        print("Simulator Plugin: stopped")

    # ── Race-event callbacks (called by TimingStation) ───────────────────────

    async def on_race_started(
        self,
        race_id: int,
        round_id: int,
        assignments: List[dict],
    ):
        """
        Called when Race Control starts a race.

        assignments: [{"transponder_id": str, "team_id": int,
                        "grid_position": int|None}, ...]
        """
        now = datetime.now()
        self._tod_offset = (
            now.hour * 3600 + now.minute * 60 + now.second + now.microsecond / 1e6
        )
        self._race_id = race_id
        self._race_end_event.clear()

        pool_set = set(self._transponder_pool)
        active = [a for a in assignments if a["transponder_id"] in pool_set]

        if not active:
            print(
                f"Simulator: no pool transponders in race {race_id} assignments "
                f"— staying idle"
            )
            return

        # ── Deltas: stable within a round, regenerated for each new round ────
        if round_id not in self._round_deltas:
            self._round_deltas[round_id] = {
                tid: round(min(6.0, max(2.0, 2.0 + random.expovariate(0.5))), 3)
                for tid in self._transponder_pool
            }
            print(f"Simulator: generated lap-time deltas for round {round_id}")
        round_deltas = self._round_deltas[round_id]
        self._round_id = round_id

        # ── First-crossing offsets (Le Mans start) ────────────────────────────
        # Sort by grid_position; teams without a position go last.
        ordered = sorted(
            active,
            key=lambda a: a["grid_position"] if a["grid_position"] is not None else 999,
        )
        n = len(ordered)
        self._current_assignments = {}
        for idx, a in enumerate(ordered):
            tid = a["transponder_id"]
            ideal = 1.0 + idx * 5.0 / max(n - 1, 1)
            offset = round(max(0.5, min(8.0, random.gauss(ideal, 0.5))), 3)
            self._current_assignments[tid] = (offset, round_deltas.get(tid, 4.0))

        print(
            f"Simulator: race {race_id} (round {round_id}) — "
            f"{len(self._current_assignments)} transponders, firing"
        )
        self._race_start_event.set()

    async def on_race_ended(self, race_id: int):
        """Called when Django signals the race has finished."""
        if self._race_id == race_id:
            print(
                f"Simulator: race {race_id} ended — "
                f"continuing for {self.post_race_duration:.0f} s"
            )
            self._race_end_event.set()

    # ── Simulation loops ──────────────────────────────────────────────────────

    async def _race_loop(self):
        """Main loop: idle → race → post-race cooldown → idle → …"""
        while self.is_reading:
            # Wait for next race
            self._race_start_event.clear()
            try:
                await self._race_start_event.wait()
            except asyncio.CancelledError:
                break

            if not self.is_reading:
                break

            # Launch one coroutine per active transponder
            self._sim_tasks = [
                asyncio.create_task(self._transponder_loop(tid, first_offset, delta))
                for tid, (first_offset, delta) in self._current_assignments.items()
            ]

            # Wait until race ends, then let the post-race window expire
            self._race_end_event.clear()
            try:
                await self._race_end_event.wait()
                await asyncio.sleep(self.post_race_duration)
            except asyncio.CancelledError:
                pass

            # Tear down transponder tasks
            for task in self._sim_tasks:
                task.cancel()
            await asyncio.gather(*self._sim_tasks, return_exceptions=True)
            self._sim_tasks = []
            print("Simulator: race simulation wound down — waiting for next race")

    async def _transponder_loop(
        self, transponder_id: str, first_offset: float, delta: float
    ):
        """Simulate one transponder for the lifetime of a race."""
        try:
            # Le Mans start delay
            await asyncio.sleep(first_offset)

            cumulative = round(first_offset, 3)
            pending_interval = cumulative  # for interval mode

            # First crossing
            if random.random() >= self.miss_probability:
                await self._fire(
                    transponder_id,
                    self._raw_time(cumulative, pending_interval),
                )
                pending_interval = 0.0

            # Continuous laps
            while True:
                lap_time = round(
                    max(
                        self.min_time,
                        random.gauss(self.min_time + delta, self.lap_sigma),
                    ),
                    3,
                )
                await asyncio.sleep(lap_time)
                cumulative = round(cumulative + lap_time, 3)
                pending_interval = round(pending_interval + lap_time, 3)

                if random.random() < self.miss_probability:
                    continue  # missed — accumulate for interval mode

                await self._fire(
                    transponder_id,
                    self._raw_time(cumulative, pending_interval),
                )
                pending_interval = 0.0

        except asyncio.CancelledError:
            pass
        except Exception as exc:
            print(f"Simulator: transponder {transponder_id} error: {exc}")

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _raw_time(self, cumulative: float, pending_interval: float) -> float:
        """Convert simulation time to the raw_time expected by the timing mode."""
        if self.timing_mode == "interval":
            return round(pending_interval, 3)
        elif self.timing_mode == "duration":
            return round(cumulative, 3)
        elif self.timing_mode == "time_of_day":
            return round((self._tod_offset + cumulative) % 86400.0, 3)
        elif self.timing_mode == "own_time":
            return round(cumulative % self.rollover_seconds, 3)
        return round(cumulative, 3)

    async def _fire(self, transponder_id: str, raw_time: float):
        await self.on_crossing(
            CrossingEvent(
                transponder_id=transponder_id,
                timestamp=datetime.now(),
                raw_time=raw_time,
                signal_strength=random.randint(80, 100),
            )
        )

    @staticmethod
    def _http_post(url: str, data: dict) -> dict:
        """Synchronous HTTP POST (runs in executor)."""
        body = json.dumps(data).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=5) as response:
            return json.loads(response.read())

    def get_status(self) -> dict:
        return {
            "plugin_type": "Simulator",
            "connected": self.is_connected,
            "reading": self.is_reading,
            "transponder_pool": len(self._transponder_pool),
            "active_transponders": len(self._current_assignments),
            "race_id": self._race_id,
            "round_id": self._round_id,
            "timing_mode": self.timing_mode,
        }
