# Migration Guide: Lap-Based Timing System

## Overview

This guide explains how to migrate your existing Go-Kart race management system to the new lap-based timing system. The migration is designed to be **backward compatible** - existing championships continue to work unchanged while new championships can use the enhanced lap-based features.

---

## Key Concepts

### Backward Compatibility Flag

The system uses a flag called `uses_legacy_session_model` on each Round:

- **`True` (default)**: Round uses the old time-only Session model
- **`False`**: Round uses the new Race model with lap tracking, transponder integration, and 7 race ending modes

### Race Ending Modes

The new system supports 7 different race ending modes:

1. **TIME_ONLY** - Positions frozen at last crossing before time expired (legacy mode)
2. **CROSS_AFTER_TIME** - Race ends when all teams cross after time limit
3. **CROSS_AFTER_LAPS** - Each team's race ends when they cross after completing required laps
4. **QUALIFYING** - Best lap time before time elapses
5. **QUALIFYING_PLUS** - F1 style: last lap must start before time expires, can finish after
6. **FULL_LAPS** - Race ends when all teams complete set number of laps
7. **AUTO_TRANSFORM** - Lap-based race auto-switches to "Cross After Time" when max time expires

---

## Migration Steps

### Step 1: Apply Database Migrations

Run the migration on your Django server:

```bash
cd /path/to/gokartrace
python manage.py migrate race
```

This creates all new database tables and fields without affecting existing data.

### Step 2: Verify Existing Data

After migration, verify that existing rounds still work:

1. Access Django admin at `/admin/`
2. Navigate to **Race → Rounds**
3. Verify all existing rounds have `uses_legacy_session_model = True`
4. Test existing race control functionality to ensure nothing broke

### Step 3: Register Transponders

Before creating lap-based races, register your timing transponders:

1. In Django admin, go to **Race → Transponders**
2. Click **Add Transponder**
3. Enter:
   - **Transponder ID**: The unique ID from your timing hardware (e.g., "023066")
   - **Description**: Human-readable label (e.g., "Transponder #1 - Red")
   - **Active**: Check this box
4. Repeat for all transponders

### Step 4: Converting Existing Championships (Optional)

⚠️ **WARNING**: Only convert championships that have **NOT started any rounds yet!**

#### Option A: Automatic Conversion (Recommended)

Use the management command for safe conversion:

```bash
# Dry run first to preview changes
python manage.py convert_to_lap_based <championship_id> --ending-mode TIME_ONLY --dry-run

# If preview looks good, run without --dry-run
python manage.py convert_to_lap_based <championship_id> --ending-mode TIME_ONLY
```

**Arguments:**
- `<championship_id>`: The ID of the championship to convert
- `--ending-mode`: Default race ending mode (default: TIME_ONLY for backward compatibility)
- `--dry-run`: Preview changes without applying them

**What it does:**
1. Validates no rounds have started
2. Sets championship default ending mode
3. Creates a Race object for each Round
4. Sets `uses_legacy_session_model = False`
5. Preserves existing time limits

#### Option B: Manual Conversion

If you prefer manual control:

1. **Update Championship** (in Django admin):
   - Edit the championship
   - Set **Default ending mode**: Choose from 7 modes (recommend TIME_ONLY initially)
   - Set **Default lap count**: e.g., 100 (can be adjusted per race)
   - Set **Default time limit**: e.g., 4 hours (inherited from round duration)
   - Save

2. **For each Round** (in Django admin):
   - Edit the round
   - **VERIFY** that `started` is NULL (round has not started)
   - Set **Uses legacy session model**: Uncheck (set to False)
   - Set **Lap count adjustment**: Leave blank to use championship default
   - Set **Time limit adjustment**: Leave blank to use round duration
   - Save

3. **Create Race objects** (Django shell):
   ```python
   from race.models import Round, Race

   round_obj = Round.objects.get(id=<round_id>)
   Race.objects.create(
       round=round_obj,
       race_type='MAIN',
       sequence_number=1,
       ending_mode=round_obj.championship.default_ending_mode,
       time_limit_override=round_obj.duration
   )
   ```

---

## Creating New Lap-Based Championships

### Step 1: Create Championship

1. In Django admin, go to **Race → Championships**
2. Click **Add Championship**
3. Fill in basic details (name, start date, etc.)
4. **New fields**:
   - **Default ending mode**: Choose race ending mode (e.g., CROSS_AFTER_TIME)
   - **Default lap count**: Set typical lap count (e.g., 100)
   - **Default time limit**: Set maximum race duration (e.g., 4:00:00)
5. Save

### Step 2: Create Rounds

1. Create rounds as usual
2. **Important**: Set `uses_legacy_session_model = False` to enable lap-based features
3. Optionally adjust lap count/time limit per round

### Step 3: Create Races within Rounds

For simple rounds (single main race):

1. In Django admin, go to **Race → Races**
2. Click **Add Race**
3. Set:
   - **Round**: Select the round
   - **Race type**: MAIN
   - **Sequence number**: 1
   - **Ending mode**: Inherits from championship (can override)
   - **Lap count override**: Leave blank to use championship default
   - **Time limit override**: Leave blank to use round duration
4. Save

For complex rounds (qualifying + main race):

Create multiple races with sequence numbers:

**Q1 (Qualifying 1)**:
- Race type: Q1
- Sequence number: 1
- Ending mode: QUALIFYING

**Q2 (Qualifying 2)**:
- Race type: Q2
- Sequence number: 2
- Ending mode: QUALIFYING

**Main Race**:
- Race type: MAIN
- Sequence number: 3
- Ending mode: CROSS_AFTER_TIME
- Depends on race: Q2 (for grid positions)

---

## Pre-Race Workflow

### 1. Transponder Matching

Before each race, associate transponders with teams:

1. Navigate to `/race/<race_id>/transponders/`
2. For each team:
   - Select team from dropdown
   - Enter kart number
   - Have team drive through start/finish line
   - System auto-detects and assigns transponder
3. Click **Lock Transponder Assignments** when done

### 2. Grid Position Setup

Set starting positions:

**Auto-assign from qualifying**:
1. Navigate to `/race/<race_id>/grid/`
2. Click **Auto-assign from Qualifying**
3. Select qualifying race
4. Positions populated automatically

**Auto-assign from championship standings**:
1. Navigate to `/race/<race_id>/grid/`
2. Click **Auto-assign from Championship**
3. Positions based on current championship points

**Manual override**:
1. Drag-and-drop positions
2. Enter override reason
3. Click **Save Changes**

**Lock grid**:
1. Review final positions
2. Click **Lock Grid**
3. Grid is now frozen and race can start

---

## During Race

### Race Control Interface

The race control interface now has **tabs** to manage screen space:

1. **Control Tab**: Start/pause/end race, pit lane management
2. **Leaderboard Tab**: Live standings, team details
3. **Laps Tab**: Lap-by-lap view, suspicious lap detection
4. **Penalties Tab**: Penalty management (existing functionality)

### Suspicious Lap Detection

The system automatically flags laps that are >2x the median lap time (indicates missed crossing):

1. Switch to **Laps Tab**
2. Suspicious laps highlighted in **red**
3. Click suspicious lap to open details
4. Click **Split Lap** to create two laps from one (corrects missed crossing)

### Public Leaderboard

For spectators and timing displays:

1. Open `/leaderboard/<race_id>/` on a separate screen
2. Full-screen real-time standings
3. Updates automatically via WebSocket

---

## Post-Race

### Verify Lap Data

1. Check **Laps Tab** for any remaining suspicious laps
2. Review and split/invalidate as needed
3. Verify all teams have correct lap counts

### Export Results

Results are stored in the database and accessible via:
- Django admin (Race → Lap Crossings)
- Existing results views (updated to show lap-based data when available)

---

## Troubleshooting

### Problem: "Cannot convert championship with started rounds"

**Cause**: The conversion command refuses to convert championships where any round has already started (to prevent data loss).

**Solution**:
- Create a new championship for lap-based timing
- Keep existing championship unchanged (it will continue to work with time-only mode)

### Problem: Transponders not detected during matching

**Cause**: Timing daemon not running or not connected.

**Solution**:
1. Verify timing daemon is running: `python timing_daemon.py --config timing_config.toml`
2. Check WebSocket connection in browser console
3. Verify transponder hardware is powered on and configured

### Problem: Suspicious laps appearing frequently

**Cause**: Transponder missed a crossing (common with low battery or signal interference).

**Solution**:
1. Use **Split Lap** feature to correct missed crossings
2. Check transponder battery level
3. Verify timing loop hardware is functioning

### Problem: Grid positions not auto-populating

**Cause**: Qualifying race not finished or no results available.

**Solution**:
1. Verify qualifying race has ended
2. Check that teams recorded valid laps in qualifying
3. Manually assign grid positions if needed

---

## Advanced Features

### Knockout Qualifying (F1 Style)

Set up multi-stage qualifying where slower drivers are eliminated:

1. Create Q1, Q2, Q3 races
2. In Django admin, create **Qualifying Knockout Rules**:
   - **Qualifying race**: Q1
   - **Eliminates to position range**: -5 to -1 (bottom 5)
   - **Sets grid positions for**: MAIN
   - **Grid position offset**: 15 (positions 16-20)

3. Repeat for Q2 eliminating next 5 to positions 11-15
4. Q3 survivors get positions 1-10

### Combined Qualifying Results

Average best laps across multiple qualifying sessions:

1. Create multiple qualifying races (Q1, Q2)
2. Use `Race.combine_qualifying_results([q1, q2], main_race)` to average times
3. Grid positions auto-assigned based on combined results

### Custom Race Dependencies

Set up complex race sequences:

1. Edit Race in admin
2. Set **Depends on race** to link races
3. Grid positions can auto-populate from dependency results

---

## Performance Considerations

### Database Queries

The system is optimized for real-time performance:

- Lap crossings use database indexes for fast queries
- Leaderboard updates are debounced (max 1/second)
- WebSocket broadcasting is asynchronous

### Scalability

Tested with:
- 30+ teams racing simultaneously
- 100+ laps per team
- Multiple concurrent races per round

### Redis Requirements

For production deployments with multiple race directors/spectators:

1. Install Redis: `apt-get install redis-server`
2. Configure Django Channels to use Redis backend
3. Restart Django application

---

## Rollback Plan

If you need to revert to time-only mode:

1. **For individual rounds**: Set `uses_legacy_session_model = True` in Django admin
2. **For entire championship**: Update all rounds to use legacy model
3. Race control will revert to time-only display
4. Lap crossing data is preserved in database

---

## Support

### Documentation

- **WebSocket Integration**: See `WEBSOCKET_INTEGRATION.md`
- **Implementation Plan**: See `.claude/plans/*.md`
- **Code Documentation**: Inline comments in `models.py`, `views.py`, `consumers.py`

### Getting Help

1. Check Django admin logs for error messages
2. Review browser console for WebSocket connection issues
3. Verify timing daemon logs for hardware communication errors
4. Contact system administrator with specific error messages

---

## Summary Checklist

Before going live with lap-based timing:

- [ ] Database migrations applied successfully
- [ ] All transponders registered in Django admin
- [ ] Timing daemon tested and connecting via WebSocket
- [ ] Test championship created with lap-based mode
- [ ] Transponder matching workflow tested
- [ ] Grid position auto-assignment tested
- [ ] Public leaderboard displays correctly
- [ ] Lap splitting feature tested
- [ ] Race directors trained on new interface tabs
- [ ] Backup of existing database created

---

**Version**: Phase 9 - Migration & Backward Compatibility
**Last Updated**: 2025-12-31
