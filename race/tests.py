# -*- encoding: utf-8 -*-
"""
Copyright (c) 2019 - present AppSeed.us
"""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

from django.test import SimpleTestCase


class TimingRaceEndedNotificationTests(SimpleTestCase):
    """The timing station must be told when a race ends, regardless of how it
    ended (timer/auto-end, apscheduler task, or a finishing crossing). Without
    this the simulator never receives on_race_ended and keeps firing crossings
    forever after a time-based race finishes.
    """

    def test_notify_sends_race_ended_to_timing_group(self):
        from race.signals import _notify_timing_race_ended

        with patch("race.signals.get_channel_layer") as mock_get_layer:
            mock_layer = MagicMock()
            mock_layer.group_send = AsyncMock()
            mock_get_layer.return_value = mock_layer

            _notify_timing_race_ended(42)

            mock_layer.group_send.assert_called_once()
            group, payload = mock_layer.group_send.call_args[0]
            self.assertEqual(group, "timing")
            self.assertEqual(payload["type"], "timing_race_ended")
            self.assertEqual(payload["race_id"], 42)


class TimingConsumerRaceEndedForwardTests(SimpleTestCase):
    """The TimingConsumer must forward a timing_race_ended channel event to the
    connected station as a signed race_ended command (mirrors race_started)."""

    def test_timing_race_ended_forwards_signed_command(self):
        from race.consumers import TimingConsumer

        consumer = TimingConsumer()
        consumer.safe_send = AsyncMock()
        consumer.sign_message = MagicMock(side_effect=lambda m: {**m, "_signed": True})

        asyncio.run(consumer.timing_race_ended({"race_id": 42}))

        consumer.safe_send.assert_awaited_once()
        sent = json.loads(consumer.safe_send.call_args[0][0])
        self.assertEqual(sent["command"], "race_ended")
        self.assertEqual(sent["race_id"], 42)
        self.assertTrue(sent["_signed"])


class LeaderboardTimerResetForwardTests(SimpleTestCase):
    """On a false start the leaderboard must receive a timer_reset so its
    countdown freezes and resets to full until the race restarts."""

    def test_timer_reset_forwarded_to_client(self):
        from race.consumers import LeaderboardConsumer

        consumer = LeaderboardConsumer()
        consumer.safe_send = AsyncMock()

        asyncio.run(consumer.timer_reset({"remaining_seconds": 1800}))

        consumer.safe_send.assert_awaited_once()
        sent = json.loads(consumer.safe_send.call_args[0][0])
        self.assertEqual(sent["type"], "timer_reset")
        self.assertEqual(sent["remaining_seconds"], 1800)


class LeaderboardPauseNotificationTests(SimpleTestCase):
    """A red-flag pause/resume must reach the leaderboard group, not just the
    round group — otherwise the leaderboard countdown keeps ticking through the
    pause (it only re-syncs on reload / tab focus). The LeaderboardConsumer
    already has a pause_update handler; the signal just never fed its group.
    """

    def _call_pause_change(self, end_value):
        from race import signals

        race = MagicMock()
        race.id = 7
        cround = MagicMock()
        cround.id = 3
        cround.active_race = race
        instance = MagicMock()
        instance.round = cround
        instance.end = end_value  # None => pause active, set => resume

        layer = MagicMock()
        layer.group_send = AsyncMock()
        with patch.object(
            signals, "get_channel_layer", return_value=layer
        ), patch.object(
            signals,
            "_build_round_update_payload",
            return_value={"is paused": end_value is None, "remaining seconds": 120},
        ):
            signals.handle_pause_change(sender=None, instance=instance)
        return layer.group_send.call_args_list

    def test_pause_notifies_leaderboard_group(self):
        calls = self._call_pause_change(end_value=None)
        groups = [c.args[0] for c in calls]
        self.assertIn("leaderboard_7", groups)
        lb = next(c for c in calls if c.args[0] == "leaderboard_7")
        self.assertEqual(lb.args[1]["type"], "pause_update")
        self.assertEqual(lb.args[1]["is paused"], True)

    def test_resume_notifies_leaderboard_group(self):
        import datetime as dt

        calls = self._call_pause_change(end_value=dt.datetime(2026, 6, 13, 12, 0, 0))
        groups = [c.args[0] for c in calls]
        self.assertIn("leaderboard_7", groups)
        lb = next(c for c in calls if c.args[0] == "leaderboard_7")
        self.assertEqual(lb.args[1]["type"], "pause_update")
        self.assertEqual(lb.args[1]["is paused"], False)


class RaceResetGridPenaltyPolicyTests(SimpleTestCase):
    """racereset must clear grid penalties (sanction='G') when resetting a
    Qualifying race (reconfigure fresh), but keep them when resetting MAIN
    (they produced that grid). Resetting a Q used to keep them, which let a
    re-added grid penalty stack into a duplicate."""

    def test_grid_penalties_survive_only_for_main_reset(self):
        from race.management.commands.racereset import grid_penalties_survive_reset

        self.assertTrue(grid_penalties_survive_reset("MAIN"))
        self.assertFalse(grid_penalties_survive_reset("Q1"))
        self.assertFalse(grid_penalties_survive_reset("Q2"))


class StandingsLapCountRuleTests(SimpleTestCase):
    """The standings lap count must count *completed laps* by lap_number, not by
    the presence of a lap_time. Red-flag in-flight and straddling laps are stored
    with lap_time=None on purpose (count the lap, void the time); counting by
    lap_time used to drop them, so the in-flight cars showed a permanent 1-lap
    deficit even though their lap_number (distance/position) was correct. The
    start passage is lap_number=0 and must still NOT count."""

    def test_completed_lap_filter_counts_by_lap_number_not_lap_time(self):
        from race.models import Race

        f = Race.completed_lap_filter()
        # Counted by lap_number: the start passage (lap_number 0) is excluded,
        # every real lap (>=1) included.
        self.assertEqual(f.get("lap_number__gte"), 1)
        # Must NOT filter on lap_time — that would drop voided red-flag laps.
        self.assertNotIn("lap_time__isnull", f)
        # Only valid crossings count (dropped extra-lap crossings excluded).
        self.assertTrue(f.get("is_valid"))


class LapPauseOverlapTests(SimpleTestCase):
    """A lap whose interval overlaps a red-flag pause is neutralised (not
    counted). With a continuous decoder clock such a lap's time would otherwise
    be inflated by the stoppage. Every lap touching the pause window is dropped;
    the first lap bounded by two post-resume crossings is the first valid one."""

    def _t(self, secs):
        import datetime as dt

        return dt.datetime(2026, 6, 13, 12, 0, 0) + dt.timedelta(seconds=secs)

    def test_overlap_detection(self):
        from race.consumers import lap_overlaps_pause

        pauses = [(self._t(100), self._t(200))]  # red flag 100s..200s
        # laps clear of the pause -> valid
        self.assertFalse(lap_overlaps_pause(pauses, self._t(0), self._t(50)))
        self.assertFalse(lap_overlaps_pause(pauses, self._t(250), self._t(300)))
        self.assertFalse(lap_overlaps_pause(pauses, self._t(200), self._t(260)))
        # laps touching the pause -> neutralised
        self.assertTrue(lap_overlaps_pause(pauses, self._t(80), self._t(150)))
        self.assertTrue(lap_overlaps_pause(pauses, self._t(120), self._t(180)))
        self.assertTrue(lap_overlaps_pause(pauses, self._t(150), self._t(250)))
        self.assertTrue(lap_overlaps_pause(pauses, self._t(50), self._t(250)))

    def test_open_pause_treated_as_ongoing(self):
        from race.consumers import lap_overlaps_pause

        pauses = [(self._t(100), None)]  # still paused
        self.assertTrue(lap_overlaps_pause(pauses, self._t(80), self._t(150)))
        self.assertFalse(lap_overlaps_pause(pauses, self._t(0), self._t(50)))


class RedFlagCrossingClassificationTests(SimpleTestCase):
    """Classify a crossing around a red flag into (should_count, void_time).

    The lap a kart is *on* when the flag falls counts whichever side of the
    flag it completes — during suspension (in-flight) or after resume
    (straddling) — but its time is void. A whole extra lap done under the
    suspension does not count. So two nose-to-tail cars split by the flag keep
    the same lap instead of getting an artificial 1-lap gap."""

    def _t(self, secs):
        import datetime as dt

        return dt.datetime(2026, 6, 13, 12, 0, 0) + dt.timedelta(seconds=secs)

    def test_normal_lap_counts_with_time(self):
        from race.consumers import classify_red_flag_crossing

        self.assertEqual(
            classify_red_flag_crossing(False, False, self._t(0), None, [], self._t(47)),
            (True, False),
        )

    def test_count_during_suspension_config_counts_everything(self):
        from race.consumers import classify_red_flag_crossing

        # Race opts to count during suspension: normal counting, time kept.
        self.assertEqual(
            classify_red_flag_crossing(
                True, True, self._t(0), self._t(10), [], self._t(47)
            ),
            (True, False),
        )

    def test_inflight_lap_during_suspension_counts_void_time(self):
        from race.consumers import classify_red_flag_crossing

        # Suspended, last crossing BEFORE the open pause start -> in-flight.
        self.assertEqual(
            classify_red_flag_crossing(
                False, True, self._t(5), self._t(40), [], self._t(45)
            ),
            (True, True),
        )

    def test_extra_lap_during_suspension_dropped(self):
        from race.consumers import classify_red_flag_crossing

        # Suspended, last crossing AFTER the open pause start -> extra lap.
        self.assertEqual(
            classify_red_flag_crossing(
                False, True, self._t(50), self._t(40), [], self._t(95)
            ),
            (False, False),
        )

    def test_suspended_with_no_previous_crossing_dropped(self):
        from race.consumers import classify_red_flag_crossing

        self.assertEqual(
            classify_red_flag_crossing(False, True, None, self._t(40), [], self._t(45)),
            (False, False),
        )

    def test_straddling_lap_after_resume_counts_void_time(self):
        from race.consumers import classify_red_flag_crossing

        pauses = [(self._t(40), self._t(100))]
        self.assertEqual(
            classify_red_flag_crossing(
                False, False, self._t(80), None, pauses, self._t(120)
            ),
            (True, True),
        )
