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
Sets `Round.started = now`. All registered-but-unstarted sessions get `start = now`. (Legacy rounds don't have a separate `armed` flag — pre-check + start go straight from "ready" to "running".)

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

---

## Transponder Management

### Transponder Matching Page

Before each race, every team must have at least one transponder assigned. Navigate to
**Race → Transponders** (`/race/<id>/transponders/`) to manage assignments.

The page shows:
- A form to assign any registered transponder to any team (scan button for live capture)
- The current assignment table with team number, kart number, transponder ID, and status
- A progress bar counting how many teams have at least one transponder assigned
- **Lock All** / individual **Replace** buttons

#### Assigning a transponder

1. Select the team from the dropdown.
2. Optionally set a kart number (defaults to the team's existing kart number, or the team number if none).
3. Choose the transponder from the dropdown or click **Scan** to capture the next crossing from the live decoder.
4. Click **Assign**.

#### Locking assignments

Once all teams are assigned, click **Lock All Assignments**. This marks every assignment as
confirmed and prevents accidental changes. The pre-race check will fail if any team has no
assignment.

#### Replacing a transponder (race director / admin only)

If a transponder fails mid-race (e.g. dead battery), a confirmed assignment can be swapped
without unlocking all assignments:

1. Find the team's row in the assignment table.
2. Click the **Replace** button (visible only on confirmed rows).
3. Select or scan the replacement transponder in the modal.
4. Click **Replace** — the new transponder takes effect immediately.

---

### Redundant Transponders (Multiple Per Team)

A team can have **more than one transponder** on the same kart. This is useful as a backup:
if one transponder fails to register for a lap, the other one will still record it.

To add a second transponder to a team that already has one, simply repeat the assign process.
The second assignment inherits the same kart number automatically.

#### How deduplication works

When two transponders cross the finish line for the same team, the timing station sends two
separate crossing events within a second or two of each other. To prevent these from being
counted as two separate laps, the system applies a **7-second deduplication window**:

- The first crossing to arrive is recorded as the lap.
- Any subsequent crossing for the same team within 7 seconds is silently discarded.

This is based on the hardware timestamp from the decoder, not the server receive time, so
minor network delays do not cause false duplicates.

#### Double transponder failure

In rare cases all transponders on a kart may fail to register for the same lap. When this happens,
the team's next crossing covers two laps — its measured time will be roughly twice a normal
lap. The system detects this automatically (> 2× the team's median lap time) and flags the
crossing as **suspicious**.

**Race control response:**

When a suspicious lap is detected, an orange alert appears at the top of the Race Control
messages panel:

> **Suspicious lap:** Team #7, Lap 23 — possible missed crossing (both transponders?).
> **[Split Lap]**

Clicking **Split Lap** splits the crossing at the midpoint: two equal half-laps are created,
the original suspicious crossing is replaced, and the alert is dismissed. If the lap was not
actually a double (e.g. the team was genuinely slow), the race director can dismiss the alert
without splitting.

Splits can also be performed after the race from the **Lap Management** page
(`/race/<id>/laps/`), which shows all crossings filtered by suspicious flag.

---

### Start Race

Pressing **Start** moves the race from "ready" into one of two armed states depending on the race's `start_mode`:

| `start_mode` | What "Start" does | When `Race.started` is set |
|---|---|---|
| `IMMEDIATE` | Sets `Race.armed = True` **and** `Race.started = now` | At click |
| `FIRST_CROSSING` | Sets `Race.armed = True` only — clock stays frozen | At first transponder crossing |

The **`armed` flag** is the gate the timing consumer uses to decide whether incoming transponder crossings should be processed. Crossings that arrive while `armed = False` are silently dropped — this is what stops a warm-up lap from accidentally starting a `FIRST_CROSSING` race before the director has actually pressed Start. Once `armed` is `True`:

- In `IMMEDIATE` mode the race is already running.
- In `FIRST_CROSSING` mode the consumer accepts the next crossing as the race start: it sets `Race.started = crossing_time` and rewrites every active `Session.start` to that same value, so any time spent on the warm-up lap before the actual start doesn't count.

Also at Start time, regardless of mode:

- First race only: sets `Round.started = now`.
- All registered sessions get `start = now` and `Session.race = active_race` (in FIRST_CROSSING mode these starts are corrected to the crossing time once it arrives).
- Clones transponder assignments from `depends_on_race` if needed.

### During the Race

Same as legacy (pit lanes, pauses, driver changes). Pauses are **round-level** — they affect all races' timers.

### End Race

- Sets `Race.ended = now`, ends all active sessions, deletes pending sessions
- If there's a **next race**: auto-advances to its pre-check state (progress badges update)
- If this was the **last race**: sets `Round.ended = now`, runs `post_race_check()` (which also auto-converts any unserved Stop & Go penalties — see [Penalty Sanctions](#penalty-sanctions))

### False Start

- Resets `Race.started = None`, `Race.armed = False`, and all session starts
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
After a qualifying race ends, results set starting grid positions for the Main race in three steps:

1. **Knockout placement** (optional): `process_qualifying_knockout()` reads any `QualifyingKnockoutRule` records on the Q-race and pins eliminated teams at fixed back-of-grid positions (`source="KNOCKOUT"`).
2. **Combined-Q ranking**: `combine_qualifying_results()` reorders the survivors by best lap time across all ended Q-races, writing positions 1..N from the front of the grid (`source="COMBINED_Q"`). KNOCKOUT placements are kept untouched; CHAMPIONSHIP / MANUAL / previous COMBINED_Q rows are wiped first to avoid `(race, position)` collisions.
3. **Grid penalties**: `apply_grid_penalties()` walks the round's `RoundPenalty` rows with `sanction='G'`, ordered by `imposed`, and pops each offender out of its current slot and reinserts it `value` positions further back. Intervening teams shift up by one. Multiple penalties on one team stack because each is applied to the post-previous grid.

Grid positions are stored in `GridPosition` and can be manually overridden via the Grid Management page. Manual edits use `source="MANUAL"` and survive subsequent recomputes only if the grid is locked; "Reset to Auto" / "Auto-Assign from Qualifying" wipe non-KNOCKOUT rows and rebuild from steps 1–3.

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

`post_race_check()` runs once when the round ends (guarded by `post_race_check_completed` flag). It checks three transgression penalties by matching `ChampionshipPenalty.penalty.name`:

| Penalty name | What it checks | Scope |
|---|---|---|
| `"required changes"` | Team completed fewer driver changes than `Round.required_changes` | Per team |
| `"time limit"` | Driver exceeded max driving time (`driver_time_limit()`) | Per driver |
| `"time limit min"` | Driver drove less than `Round.limit_time_min` | Per driver |

Penalties create `RoundPenalty` records. If the penalty's `option` is `"per_hour"`, the value is multiplied by the round duration in hours.

### Time-in-lieu conversion

After the transgression checks, `post_race_check()` also converts any **unserved Stop & Go** penalties (sanction `S` or `D`, `RoundPenalty.served IS NULL`) into equivalent **time penalties** under the championship's `time_in_lieu` mandatory penalty:

- A new `RoundPenalty` is created with `sanction='T'`, `value` set to the original S&G duration in seconds, and `served=now` (post-race penalties have nothing to "serve").
- The original S&G is marked `served=now` and its `PenaltyQueue` row is removed.
- `time_in_lieu` is auto-seeded by `setup_essential_data` and the per-championship `ChampionshipPenalty` row is auto-created on first use.

The standings calculator already adds sanction-`T` values into each team's `total_time`, so converted penalties appear in the leaderboard without further action.

### Driving time limit calculation

`Round.driver_time_limit(team)` returns `(limit_type, max_timedelta)`:

| `limit_method` | `limit_value` | Result |
|---|---|---|
| `"none"` | — | No limit |
| `"time"` | N | Fixed N minutes |
| `"percent"` | N | `(round.duration / driver_count) * (1 + N/100)` |

The `limit_type` (`"race"` or `"session"`) determines whether the check is against total driving time or per-stint time.

---

## Penalty Sanctions

Every `ChampionshipPenalty` carries a one-character `sanction` code that determines what the penalty does and where it can be issued:

| Code | Name | Effect | Where issued |
|---|---|---|---|
| `S` | Stop & Go | Queued on the S&G station; team must serve while race is running | Race Control during the race |
| `D` | Self Stop & Go | Same queue, but no victim required (driver-error infringement) | Race Control during the race |
| `L` | Laps | Subtracted from `laps_completed` in standings | Race Control during the race; Setup Round / Fix → Lap & Time Penalties (post-race, pre-confirm) |
| `P` | Post Race Laps | Same effect as `L`; auto-created by `post_race_check()` for transgressions | Auto; or manually via the Lap & Time Penalties page |
| `T` | Time Penalty | Adds N seconds to `total_time` in standings | Setup Round / Fix → Lap & Time Penalties (post-race, pre-confirm); auto-created by time-in-lieu conversion |
| `G` | Grid Penalty | Moves the team back N positions on the Main grid (sequential, in `imposed` order) | Race Control during a Q-race; Setup Round / Fix → Grid Penalties (any time before the Main grid is locked) |

`L`, `P`, and `T` only apply to the Main race standings. `G` only applies to the Main race grid. Qualifying standings ignore all of them.

A **race reset** (`./race-manager manage racereset`) clears `S/D/L/P/T` rows for the round but keeps `G` rows, since grid penalties are pre-race setup that should still be in effect when the grid is rebuilt.

---

## Race Director Menus

Beyond the always-visible navigation, two menus carry race-day actions.

### Setup Round

Visible to users in the **Admin** group. The Race-Director-only entries are gated separately and adapt to the active round's state:

| Entry | Visible when | Purpose |
|---|---|---|
| Manage Round / Manage Round Team | Always (Admin) | Configure rounds and round teams |
| Transponder Matching | Active timing race exists | Assign + lock transponders before pre-check |
| Grid Management | Active timing race exists | Manual grid edits, lock/unlock |
| **Grid Penalties** | Main race exists, hasn't started, grid not locked | Add/remove sanction-`G` penalties; pre-selected to the active round's Main race |
| **Lap & Time Penalties** | Main race ended **and** round results not yet confirmed | Add/remove sanction-`L`/`P`/`T` penalties; pre-selected to the active round's Main race |
| Race Control | Active race exists (RD) | The live race-control dashboard |

The two penalty entries appear only during their respective windows and disappear as soon as the state changes (grid locked, race started, results confirmed). They both use `?race_id=<active_main_race_id>` so the page opens straight on the relevant Main race.

### Fix

Visible to users in the **Race Director**, **Queue Scanner**, or **Driver Scanner** groups. Hidden by default — toggle with **Ctrl + Shift + F**. Always available regardless of round state, so it can be used to clean up after a finished round.

| Entry | Group | Purpose |
|---|---|---|
| Scan In | Queue Scanner | Manually add/remove a driver from the pit-lane queue |
| Scan Out | Driver Scanner | Force-end an active driver session |
| Lap Fix | Race Director | Split / merge lap crossings on a recent or live race |
| Lap & Time Penalties | Race Director | Same as the Setup Round entry but with a race picker — useful for editing penalties on an *earlier* round whose results are still under review |
| Grid Penalties | Race Director | Same as the Setup Round entry but with a race picker — useful when no active round exists or the Main is in a different round |

The Setup Round and Fix entries hit the same backend endpoints (`fix_penalties`, `fix_grid_penalties` and their `_create` / `_delete` siblings); the only difference is whether a race is pre-selected. Both server endpoints enforce the same state gates (race ended / not started, results not confirmed, grid not locked), so URL fiddling can't bypass them.

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
