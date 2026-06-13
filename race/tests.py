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
