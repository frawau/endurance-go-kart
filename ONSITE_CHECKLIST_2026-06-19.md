# On-Site Checklist — 2026-06-19 (Pattaya), day before race (2026-06-20)

**Goal:** shake down the **production server** (LAN-only at the site) on merged main with a
short **20-min race, Test championship**. Top priority is the one path never run on real
hardware: a **real red flag**. Everything else is regression confirmation.

> Reminder: production = LAN-only at the site. `ezgokart` is only the internet results
> mirror — **do not touch its DB**.

---

## A. Deploy & infra (production server, on the LAN)

- [ ] Production server reachable on the LAN; `cd` to the repo.
- [ ] `git pull` → on **main**, HEAD = **`744185d`** (PR #19 merge). Confirm `git log --oneline -1`.
- [ ] `sudo ./race-manager rebuild` (Docker; runs migrations automatically).
- [ ] `sudo ./race-manager deploy-timing` (native timing-station daemon — separate from the rebuild).
- [ ] Containers up: `docker compose ps` → appseed_app, nginx, postgres, redis (+ acme_sh if SSL).
- [ ] **redis pinned <6:** `docker exec -i appseed_app pip show redis` → Version 5.x (avoids the WS-storm landmine).
- [ ] `docker exec -i appseed_app python manage.py check` → no issues.
- [ ] No unapplied migrations.
- [ ] **`DEBUG = False`** on prod (this was the outstanding prod-only fix — verify it's off).

## B. Timing hardware

- [ ] `systemctl is-active timing-station.service` → active/running.
- [ ] nettag decoder connected; **mode = `own_time`**; **proxy NOT in use** (direct nettag).
- [ ] `TIMING_HMAC_SECRET` present in both `.env` and `core/settings.py` (HMAC must match).
- [ ] Fire a few test transponder passes → crossings appear in race control / leaderboard (decoder → app path alive).

## C. Race config — Test championship, 20-min

- [ ] Select the **Test championship**; create/confirm the round.
- [ ] MAIN race: ending **CROSS_AFTER_LEADER**, **time limit 20 min**, start mode **FIRST_CROSSING** (matches race-day config).
- [ ] Decide `required_changes`: set **0** if you won't do a pit/driver change in 20 min (avoids the post-race lap penalty), or **1** if you want to test one change + the scan app.
- [ ] Transponders assigned to the Test teams.
- [ ] **Lock the grid first, then lock the transponders** (grid lock doesn't unlock transponders; order matters).

## D. Pre-race

- [ ] Run the pre-race check; resolve any flagged items.
- [ ] Leaderboard (trackside + public) loads and shows the grid.
- [ ] Race control buttons present; confirm **"Red Flag"** (red) and **"End Race"** (dark, needs click+confirm).

---

## E. During the run — tests in priority order

### E1. 🔴 RED FLAG (highest priority — never tested on real hardware)
- [ ] Let cars complete a couple of laps and bunch into a pack.
- [ ] With a tight nose-to-tail group **straddling the S/F line**, press **Red Flag**.
- [ ] **Verify on the leaderboard:**
  - [ ] The whole lead-lap pack stays on the **same lap** — no car stuck a lap down (no phantom split).
  - [ ] Cars caught mid-lap at the line get **credited** (lap count ticks up; their last-lap time shows **"—"**, time voided).
  - [ ] Countdown clock **freezes**.
- [ ] Resume the race; verify racing continues, lap counts keep matching, **no dropped/duplicated laps**, no cascade.
- [ ] (If feasible) a second red flag to confirm repeatability.

### E2. False start
- [ ] Trigger a **false start** shortly after the green.
- [ ] Clock **resets to full and freezes**; field returns to **grid order** (note: display may briefly show team-number order until the 2nd crossing — cosmetic, known).
- [ ] Crossings during the abort are **ignored** (no phantom laps after restart).
- [ ] Restart cleanly from the grid.

### E3. Driver change / pit lane (only if `required_changes` ≥ 1)
- [ ] Pit-lane open/close window behaves.
- [ ] Scan in/out via the **phone app (`../ScanFlutter`)** → driver swap registers; pit queue updates.
- [ ] Driver min/max drive-time tracking looks right (esp. across the red-flag pause).

### E4. Stop-and-go (optional)
- [ ] Issue an S&G penalty → appears on the call display; serving clears it.

### E5. Displays
- [ ] Trackside + public leaderboard lap counts and positions match what you see on track.

## F. Race end (CROSS_AFTER_LEADER + 20-min limit)

- [ ] After 20 min, race **does not end immediately** — continues until the leader crosses, then each team's race ends as they cross after the leader.
- [ ] Race ends when all have crossed (or the safety timeout).
- [ ] **No crossings recorded after the race ends** (timing stops cleanly).
- [ ] Final standings correct; positions sensible.
- [ ] Run the post-race check; penalties (if any) apply as expected.

---

## G. Known issues / watch-outs (not blockers)

- `/all_pitlanes/` does **not** auto-reconnect after an app/WS drop → manual page reload.
- False-start grid-order display reverts to team-number order until the 2nd crossing (cosmetic).
- If you skip driver changes with `required_changes` > 0, every team takes a post-race lap penalty — expected, not a bug.

## H. Don'ts / safety

- [ ] **Never deploy (rebuild) while a race is live** — only between runs.
- [ ] Don't touch the `ezgokart` mirror DB.
- [ ] If anything scores wrong, you can `racereset` between runs (MAIN reset keeps grid penalties; Q reset clears them).

---

### Quick verdict for go/no-go on race day
- ✅ Red flag keeps the pack together + clean resume → the headline new feature works on real hardware.
- ✅ False start, finish, displays behave → no regression from the new code.
- Anything red here → note it; there's a day to react before 2026-06-20.
