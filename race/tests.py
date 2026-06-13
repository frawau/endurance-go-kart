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
