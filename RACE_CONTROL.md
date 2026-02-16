# Race Control — How It Works

This document explains how race control operates, covering both **legacy (time-only)** rounds and **lap-based (multi-race)** rounds.

---

## Two Modes of Operation

A Round operates in one of two modes, selected via `uses_legacy_session_model`:

| | Legacy (time-only) | Lap-based (multi-race) |
|---|---|---|
| `uses_legacy_session_model` | `True` (default) | `False` |
| Race objects | None — round is the race | 1+ Race objects (Q1, Q2, ..., MAIN) |
| Timing source | Wall clock only | Transponder crossings + wall clock |
| Transponder required | No | Yes — every team must have one |
| Race ending | Manual "End Race" button | Manual or automatic (per ending mode) |
| Timer shows | Round duration countdown | Active race duration countdown |

The mode is configured when editing a round ("Lap-based timing" checkbox). Once a race has started, the mode cannot be changed.

---

## Legacy Round Flow

A legacy round has no Race objects. The entire round is one continuous session.

```
[Initial] ──Pre-check──▶ [Ready] ──Start──▶ [Running] ──End──▶ [Ended]
                                       │          ▲
                                       │          │
                                   Pause ──▶ [Paused] ──Resume──┘
```

### Pre-Race Check
Validates:
- Every team has exactly one registered (scanned-in) driver
- All drivers have a plausible weight (> 10 kg)

On success: sets `Round.ready = True`, creates ChangeLane objects (one per pit lane).

### Start Race
Sets `Round.started = now`. All registered-but-unstarted sessions get `start = now`.

### During the Race
- **Pit lane**: opens after `pitlane_open_after`, closes `pitlane_close_before` the end
- **Driver changes**: drivers register via QR scan, enter change lanes, swap on track
- **Pausing**: creates a `round_pause` record; timer freezes; pit lane frozen
- **Resuming**: closes the open pause record; timer resumes

### End Race
Sets `Round.ended = now`. Ends all active sessions. Runs `post_race_check()` for penalties.

### False Start / False Restart
- **False Start** (available for 15 s after start): resets `Round.started` and all session starts to `None`
- **False Restart** (available for 15 s after resume): re-opens the most recent pause

---

## Lap-Based (Multi-Race) Round Flow

A lap-based round contains one or more **Race** objects that run sequentially. The round-level timer tracks the currently active race.

```
        ┌────────────────── For each Race ──────────────────┐
        │                                                   │
[Initial] ──Pre-check──▶ [Ready] ──Start──▶ [Running] ──End──▶ [Next race?]
                                       │          ▲               │    │
                                       │          │              Yes   No
                                   Pause ──▶ [Paused] ──Resume──┘  │    │
                                                                    │    ▼
                                                              [Initial] [Round Ended]
                                                              (next race)
```

### Race Sequence

Races execute in `sequence_number` order. A typical configuration:

| Sequence | Type | Ending Mode | Duration |
|---|---|---|---|
| 1 | Q1 (Qualifying 1) | QUALIFYING | 15:00 |
| 2 | MAIN | TIME_ONLY | 04:00:00 |

Or with multiple qualifying sessions:

| Sequence | Type | Ending Mode | Duration |
|---|---|---|---|
| 1 | Q1 | QUALIFYING | 15:00 |
| 2 | Q2 | QUALIFYING | 15:00 |
| 3 | MAIN | CROSS_AFTER_TIME | 04:00:00 |

The `active_race` property always returns the first Race with `ended = NULL`, ordered by `sequence_number`.

### Pre-Race Check (per race)

Runs the same driver/weight checks as legacy, **plus**:
- Every non-retired team must have a `RaceTransponderAssignment` for the active race

On success: sets `Round.ready = True`, creates ChangeLanes, sets `Race.ready = True`.

For **subsequent races** (e.g., MAIN after Q1), the race director must:
1. Have drivers register again (scan in)
2. Click Pre-Race Check again

Transponder assignments are automatically cloned from `depends_on_race` at start time if not already present.

### Start Race

- Sets `Race.started = now`
- First race only: also sets `Round.started = now`
- All registered sessions get `start = now` and `Session.race = active_race`
- Clones transponder assignments from `depends_on_race` if needed

### During the Race

Same as legacy (pit lanes, pauses, driver changes). Pauses are **round-level** — they affect all races' timers.

### End Race

- Sets `Race.ended = now`, ends all active sessions, deletes pending sessions
- If there's a **next race**: auto-advances to its pre-check state (progress badges update)
- If this was the **last race**: sets `Round.ended = now`, runs `post_race_check()`

### False Start

- Resets `Race.started = None` and all session starts
- If no other race has ever started: also resets `Round.started = None`

---

## Race Ending Modes

Each Race has an `ending_mode` that determines when/how it finishes. The race director always has the manual "End Race" button, but some modes can also trigger automatic endings via `is_race_finished()`.

| Mode | When it ends | Typical use |
|---|---|---|
| **TIME_ONLY** | Timer reaches zero; positions frozen at last crossing before time | Simple endurance races |
| **CROSS_AFTER_TIME** | Timer reaches zero, then leader crosses line, then all teams cross | Endurance with final-lap completion |
| **CROSS_AFTER_LAPS** | Each team finishes when they complete required laps and cross | Sprint races |
| **FULL_LAPS** | Race ends when all teams have completed required laps | Equal-distance races |
| **QUALIFYING** | Timer reaches zero; all laps finishing before time count | Qualifying sessions |
| **QUALIFYING_PLUS** | Timer reaches zero; laps *started* before time can still finish | F1-style qualifying |
| **AUTO_TRANSFORM** | Lap-based until laps complete OR time expires → becomes CROSS_AFTER_TIME | Hybrid races |

### Parameter Resolution

Each mode uses a **time limit** and/or **lap count**. These resolve with this precedence (highest wins):

1. `Race.time_limit_override` / `Race.lap_count_override`
2. `Round.time_limit_adjustment` / `Round.lap_count_adjustment`
3. `Championship.default_time_limit` / `Championship.default_lap_count`

If nothing is set, time limit defaults to 4 hours and lap count to 0.

---

## Qualifying Sessions

Qualifying races (Q1, Q2, Q3) have special behaviour:

### What's different during qualifying
- **Leaderboard** shows standings sorted by best lap time
- **Driver changes** are allowed (pit lanes work normally)
- **Session.race** is set to the qualifying Race object

### What's isolated from the main race
- Driver changes during qualifying **do not count** towards `required_changes`
- Driver time during qualifying **does not count** towards `time_spent` penalty checks
- Both filters use: `Q(race__race_type="MAIN") | Q(race__isnull=True)`

### Grid positions
After a qualifying race ends, results can set starting grid positions for subsequent races via:
- **Best time method**: `combine_qualifying_results()` picks each team's best lap
- **Elimination method**: `QualifyingKnockoutRule` records define cutoff positions

Grid positions are stored in `GridPosition` and can be manually overridden.

---

## Timer System

### How the countdown works

The `timer_widget` template tag renders a `<span>` with JSON configuration. The JavaScript `timer-widget.js` reads this config and manages the countdown/countup display.

For **legacy rounds**: the timer widget receives the Round instance.
For **lap-based rounds**: it receives the active Race instance.

Both expose the same interface: `duration`, `time_elapsed`, `started`, `ended`, `is_paused`.

### WebSocket updates

All timer state flows through a single WebSocket channel (`round_{id}`). The `_build_round_update_payload()` function in `signals.py` builds the payload:

- For lap-based rounds with an active race: uses `Race.duration` and `Race.time_elapsed`
- For legacy rounds or when all races are done: uses `Round.duration` and `Round.time_elapsed`

Extra fields for multi-race UI:
- `active_race_type`: e.g., `"Q1"`, `"MAIN"`, or `null`
- `active_race_label`: e.g., `"Qualifying 1"`, `"Main Race"`, or `null`
- `has_more_races`: `true` if there's still an unfinished race

### Pause handling

Pauses are always round-level (`round_pause` model). `Race.time_elapsed` correctly intersects pause windows with the race's own start/end window, so a pause during Q1 that extends into MAIN is accounted for correctly in each race's timer.

---

## Post-Race Penalties

`post_race_check()` runs once when the round ends (guarded by `post_race_check_completed` flag). It checks three penalty types by matching `ChampionshipPenalty.penalty.name`:

| Penalty name | What it checks | Scope |
|---|---|---|
| `"required changes"` | Team completed fewer driver changes than `Round.required_changes` | Per team |
| `"time limit"` | Driver exceeded max driving time (`driver_time_limit()`) | Per driver |
| `"time limit min"` | Driver drove less than `Round.limit_time_min` | Per driver |

Penalties create `RoundPenalty` records. If the penalty's `option` is `"per_hour"`, the value is multiplied by the round duration in hours.

### Driving time limit calculation

`Round.driver_time_limit(team)` returns `(limit_type, max_timedelta)`:

| `limit_method` | `limit_value` | Result |
|---|---|---|
| `"none"` | — | No limit |
| `"time"` | N | Fixed N minutes |
| `"percent"` | N | `(round.duration / driver_count) * (1 + N/100)` |

The `limit_type` (`"race"` or `"session"`) determines whether the check is against total driving time or per-stint time.

---

## Configuration Summary

### Championship level (locked for all rounds)
- `default_ending_mode` — base ending mode for races
- `default_lap_count` — base lap target
- `default_time_limit` — base time limit

### Round level
- `duration` — total round duration (also used as MAIN race time limit)
- `uses_legacy_session_model` — toggle between legacy and lap-based
- `change_lanes` — number of pit lane positions (1-4)
- `pitlane_open_after` / `pitlane_close_before` — pit lane window
- `required_changes` — minimum driver swaps
- `limit_time` / `limit_method` / `limit_value` — max driving time rules
- `limit_time_min` — minimum driving time per driver
- `weight_penalty` — ballast rules by driver weight
- `lap_count_adjustment` / `time_limit_adjustment` — override championship defaults

### Race level (lap-based only)
- `race_type` — Q1/Q2/Q3/MAIN/PRACTICE
- `sequence_number` — execution order
- `ending_mode` — how this specific race ends
- `lap_count_override` / `time_limit_override` — override round/championship values
- `depends_on_race` — for transponder cloning and grid positions
- `count_crossings_during_suspension` — whether paused laps count

### Created via round edit form
When "Lap-based timing" is enabled, the round edit form creates Race objects:
- `qualifying_count` qualifying races (Q1, Q2, ...) with configurable durations
- 1 MAIN race with `time_limit_override = Round.duration`
- Optional `QualifyingKnockoutRule` records for elimination-style qualifying
