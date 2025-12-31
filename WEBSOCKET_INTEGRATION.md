# WebSocket Integration - Lap-Based Timing System

## Overview

The lap-based timing system uses Django Channels WebSockets for real-time communication between:
- Timing daemon (external Python process)
- Django application (race control, leaderboard)
- Race directors and spectators (browser clients)

## WebSocket Consumers

### 1. TimingConsumer (`/ws/timing/`)

**Purpose**: Receives lap crossing data from external timing daemon

**Message Flow**:
```
Timing Daemon → TimingConsumer → [Leaderboard, Race Control]
```

**Incoming Messages** (from timing daemon):
- `lap_crossing`: Transponder detected crossing start/finish line
  ```json
  {
    "type": "lap_crossing",
    "race_id": 123,
    "team_number": 5,
    "kart_number": 12,
    "transponder_id": "023066",
    "timestamp": "2025-12-31T15:30:45.123456",
    "raw_time": 1234.567,
    "signal_strength": 95,
    "hmac_signature": "..."
  }
  ```

- `warning`: Unknown transponder detected
  ```json
  {
    "type": "warning",
    "message": "Unknown transponder: 023066",
    "transponder_id": "023066",
    "timestamp": "2025-12-31T15:30:45.123456",
    "hmac_signature": "..."
  }
  ```

- `connected`: Daemon connected successfully
- `response`: Command acknowledgment from daemon

**Outgoing Messages** (to timing daemon):
- Commands via `send_command()`:
  - `start_race`: Begin reading transponders
  - `end_race`: Stop reading transponders
  - `update_assignments`: Update transponder-to-team mapping
  - `get_status`: Query daemon status

**Broadcasting**:
After processing lap crossing, broadcasts to:
1. **Leaderboard group** (`leaderboard_{race_id}`):
   ```json
   {
     "type": "lap_crossing_update",
     "crossing_data": {
       "team_number": 5,
       "lap_number": 12,
       "lap_time": "0:01:23.456"
     }
   }
   ```

2. **Round group** (`round_{round_id}`):
   ```json
   {
     "type": "race_lap_update",
     "race_id": 123,
     "team_number": 5,
     "lap_number": 12,
     "is_suspicious": false
   }
   ```

3. **Race finished** (when race ends):
   ```json
   {
     "type": "race_finished",
     "race_id": 123,
     "race_type": "MAIN"
   }
   ```

**Processing**:
1. Verifies HMAC signature (security)
2. Creates `LapCrossing` database record
3. Calculates lap number and lap time
4. Detects suspicious laps (>2x median time)
5. Checks race suspension status
6. Broadcasts updates to subscribers
7. Checks if race is finished

---

### 2. LeaderboardConsumer (`/ws/leaderboard/<race_id>/`)

**Purpose**: Real-time leaderboard updates for public displays

**Message Flow**:
```
TimingConsumer → LeaderboardConsumer → Browser (Public Display)
```

**Connection**:
- Joins group: `leaderboard_{race_id}`
- Sends initial standings on connect

**Incoming Messages** (from channel layer):
- `lap_crossing_update`: New lap recorded
  - Triggers `calculate_race_standings()`
  - Debounced to max 1 update/second

**Outgoing Messages** (to browser):
- `standings_update`: Current race standings
  ```json
  {
    "type": "standings_update",
    "standings": [
      {
        "position": 1,
        "team_number": 5,
        "team_name": "Team Alpha",
        "laps_completed": 12,
        "total_time": 1234.567,
        "total_time_formatted": "0:20:34",
        "last_lap_time_formatted": "0:01:42",
        "gap_to_leader": "—",
        "position_change": 2
      },
      ...
    ]
  }
  ```

**Debouncing**:
- Maximum 1 update per second to prevent flooding
- Uses `_last_update` timestamp check

---

### 3. RoundConsumer (`/ws/round/<round_id>/`)

**Purpose**: Race control interface for directors

**Message Flow**:
```
[Race Control UI, TimingConsumer, StopAndGo] ↔ RoundConsumer ↔ Race Directors
```

**Incoming Messages** (from browser):
- Race control commands (existing)
- Penalty management (existing)
- Stop & Go integration (existing)

**Incoming Messages** (from channel layer):
- `race_lap_update`: Lap crossing notification
  ```json
  {
    "type": "race_lap_update",
    "race_id": 123,
    "team_number": 5,
    "lap_number": 12,
    "is_suspicious": false
  }
  ```

- `race_finished`: Race completion notification
  ```json
  {
    "type": "race_finished",
    "race_id": 123,
    "race_type": "MAIN"
  }
  ```

**Outgoing Messages** (to browser):
- Broadcasts lap updates to race control interface
- Notifies when race is finished
- Existing penalty and status updates

---

### 4. StopAndGoConsumer (`/ws/stopandgo/`)

**Purpose**: Stop & Go penalty station communication (existing)

**Integration**: Works alongside timing system for penalty management during lap-based races

---

## Channel Groups

### Group Naming Convention

- `leaderboard_{race_id}`: All leaderboard displays for a specific race
- `round_{round_id}`: Race control interfaces for a round
- `stopandgo`: Stop & Go penalty station(s)

### Group Membership

**LeaderboardConsumer**:
- Joins: `leaderboard_{race_id}`
- Receives: `lap_crossing_update`

**RoundConsumer**:
- Joins: `round_{round_id}`
- Receives: `race_lap_update`, `race_finished`, `penalty_*`

**TimingConsumer**:
- Does not join groups (sends only)
- Broadcasts to: `leaderboard_{race_id}`, `round_{round_id}`

---

## Security

### HMAC Signature Verification

**Timing Daemon ↔ Django**:
- All messages signed with HMAC-SHA256
- Shared secret: `settings.TIMING_HMAC_SECRET`
- Same pattern as Stop & Go station
- Prevents unauthorized commands/data

**Verification Process**:
1. Extract `hmac_signature` from message
2. Remove signature from data
3. Serialize data as JSON (deterministic order)
4. Calculate expected signature
5. Compare using `hmac.compare_digest()` (timing-attack safe)

### Stop & Go Integration

Uses same HMAC secret for consistent security across all external systems.

---

## Data Flow Example

### Complete Lap Crossing Flow

```
1. Transponder crosses line
   ↓
2. Timing daemon detects crossing
   ↓
3. Daemon sends signed message to TimingConsumer
   ↓
4. TimingConsumer verifies HMAC
   ↓
5. TimingConsumer creates LapCrossing record
   ↓
6. TimingConsumer checks for suspicious lap
   ↓
7. TimingConsumer broadcasts to:
   - leaderboard_{race_id} group
   - round_{round_id} group
   ↓
8. LeaderboardConsumer receives update
   ↓
9. LeaderboardConsumer recalculates standings (debounced)
   ↓
10. LeaderboardConsumer sends to browser clients
    ↓
11. RoundConsumer receives update
    ↓
12. RoundConsumer sends to race control
    ↓
13. Browser updates UI in real-time
```

### Race Completion Flow

```
1. Lap crossing triggers race finish check
   ↓
2. Race.is_race_finished() evaluates ending mode
   ↓
3. If finished, TimingConsumer broadcasts to round group
   ↓
4. RoundConsumer receives race_finished
   ↓
5. Race control UI shows race completion
   ↓
6. Director can end race or start next race
```

---

## Performance Considerations

### Debouncing
- LeaderboardConsumer: Max 1 update/second
- Prevents flooding during heavy traffic (multiple crossings/second)

### Database Queries
- LapCrossing creation: Single INSERT per crossing
- Suspicious lap detection: Queries existing valid laps (indexed)
- Standings calculation: Prefetched to minimize N+1 queries

### Channel Layer
- Uses Redis backend (recommended)
- Async message delivery
- Automatic reconnection handling

---

## Error Handling

### TimingConsumer
- Invalid HMAC: Log warning, ignore message
- Unknown transponder: Send warning to race control
- Race not found: Log error, ignore message
- Database errors: Log exception, continue operation

### LeaderboardConsumer
- Race not found: Return empty standings
- Calculation errors: Return cached/previous standings

### RoundConsumer
- Existing error handling maintained
- Race lap updates: Fire-and-forget (won't block)

---

## Testing

### Manual Testing
1. Start timing daemon: `python timing_daemon.py --config timing_config.toml`
2. Open race control: `/racecontrol/`
3. Open leaderboard: `/leaderboard/<race_id>/`
4. Trigger lap crossings via simulator or real hardware
5. Verify updates appear in both interfaces

### WebSocket Debugging
```javascript
// Browser console
ws = new WebSocket('ws://localhost:8000/ws/leaderboard/123/');
ws.onmessage = (e) => console.log(JSON.parse(e.data));
```

### Channel Layer Testing
```python
# Django shell
from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync

channel_layer = get_channel_layer()
async_to_sync(channel_layer.group_send)(
    'leaderboard_123',
    {'type': 'lap_crossing_update', 'crossing_data': {...}}
)
```

---

## Future Enhancements

### Potential Additions
1. **Transponder auto-detection**: Daemon broadcasts detected transponders during matching phase
2. **Live timing API**: REST endpoint for external timing displays
3. **Historical replay**: Replay lap crossings from database
4. **Multi-race monitoring**: Single interface showing all active races
5. **Alert system**: Push notifications for suspicious laps, race completion

### Scalability
- Current: Single Redis channel layer
- Future: Redis Cluster for horizontal scaling
- Consider: Separate channel layers per race for isolation
