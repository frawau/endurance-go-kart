import asyncio
import json
import logging
import time
import uuid
import datetime as dt
import hmac
import hashlib
from django.conf import settings

_log = logging.getLogger(__name__)
from channels.generic.websocket import AsyncWebsocketConsumer
from .models import (
    ChangeLane,
    round_team,
    team_member,
    championship_team,
    Round,
    Race,
    Session,
    Transponder,
    RaceTransponderAssignment,
    LapCrossing,
    GridPosition,
    ChampionshipPenalty,
    RoundPenalty,
    PenaltyQueue,
    MandatoryPenalty,
)
from django.template.loader import render_to_string
from channels.db import database_sync_to_async
from django.db.models import Count, F, Q


class SafeSendMixin:
    """Catch RuntimeError when sending to a disconnected WebSocket client."""

    async def safe_send(self, text_data):
        try:
            await self.send(text_data=text_data)
        except RuntimeError:
            pass


class EmptyTeamsConsumer(SafeSendMixin, AsyncWebsocketConsumer):
    async def connect(self):
        # Get the current round
        self.current_round = await self.get_current_round()

        if not self.current_round:
            # No active round found, close connection
            await self.close(code=4000)
            return

        self.round_id = self.current_round.id
        self.room_group_name = f"empty_teams_{self.round_id}"

        # Join room group
        await self.channel_layer.group_add(self.room_group_name, self.channel_name)

        await self.accept()

        # Send initial empty teams list
        empty_teams = await self.get_empty_teams(self.round_id)
        await self.safe_send(
            json.dumps({"type": "empty_teams_list", "teams": empty_teams})
        )

    async def disconnect(self, close_code):
        # Leave room group
        if hasattr(self, "room_group_name"):
            await self.channel_layer.group_discard(
                self.room_group_name, self.channel_name
            )

    # Receive message from WebSocket
    async def receive(self, text_data):
        data = json.loads(text_data)
        action = data.get("action")

        if action == "delete_empty_teams":
            # Delete all empty teams for current round
            deleted_count = await self.delete_empty_teams(self.round_id)

            # Send message to room group
            await self.channel_layer.group_send(
                self.room_group_name,
                {
                    "type": "system_message",
                    "message": f"Deleted {deleted_count} empty teams",
                    "tag": "success" if deleted_count > 0 else "info",
                },
            )

            # No need to broadcast empty teams list here
            # The signal handlers will automatically do it

        elif action == "delete_single_team":
            team_id = data.get("team_id")
            if team_id:
                success = await self.delete_single_team(team_id)

                # Send message to room group
                await self.channel_layer.group_send(
                    self.room_group_name,
                    {
                        "type": "system_message",
                        "message": (
                            "Team deleted successfully"
                            if success
                            else "Failed to delete team"
                        ),
                        "tag": "success" if success else "danger",
                    },
                )

                # No need to broadcast empty teams list here
                # The signal handlers will automatically do it

    # Receive message from room group
    async def empty_teams_list(self, event):
        # Send teams list to WebSocket
        await self.safe_send(
            json.dumps({"type": "empty_teams_list", "teams": event["teams"]})
        )

    # Send system message
    async def system_message(self, event):
        # Send message to WebSocket
        await self.safe_send(
            json.dumps(
                {
                    "type": "system_message",
                    "message": event["message"],
                    "tag": event["tag"],
                }
            )
        )

    # Database operations
    @database_sync_to_async
    def get_current_round(self):
        end_date = dt.date.today()
        start_date = end_date - dt.timedelta(days=1)
        return Round.objects.filter(
            Q(start__date__range=[start_date, end_date]) & Q(ended__isnull=True)
        ).first()

    @database_sync_to_async
    def get_empty_teams(self, round_id):
        teams_without_members = list(
            round_team.objects.filter(round_id=round_id)
            .annotate(member_count=Count("team_member"))
            .filter(member_count=0)
            .select_related("team__championship", "team__team")
        )

        return [
            {
                "id": rt.id,
                "team_name": rt.team.team.name,
                "number": rt.team.number,
                "championship_name": rt.team.championship.name,
            }
            for rt in teams_without_members
        ]

    @database_sync_to_async
    def delete_empty_teams(self, round_id):
        result = (
            round_team.objects.filter(round_id=round_id)
            .annotate(member_count=Count("team_member"))
            .filter(member_count=0)
            .delete()
        )

        # Return the count of deleted teams
        return result[0] if result else 0

    @database_sync_to_async
    def delete_single_team(self, team_id):
        try:
            rt = round_team.objects.get(id=team_id)
            if team_member.objects.filter(team=rt).count() == 0:
                rt.delete()
                return True
            return False
        except round_team.DoesNotExist:
            return False


class ChangeLaneConsumer(SafeSendMixin, AsyncWebsocketConsumer):
    async def connect(self):
        self.lane_number = self.scope["url_route"]["kwargs"]["pitlane_number"]
        self.lane_group_name = f"lane_{self.lane_number}"

        await self.channel_layer.group_add(self.lane_group_name, self.channel_name)
        await self.accept()

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard(self.lane_group_name, self.channel_name)

    async def lane_update(self, event):
        lane_html = event["lane_html"]
        await self.safe_send(
            json.dumps({"type": "lane.update", "lane_html": lane_html})
        )

    async def rclane_update(self, event):
        lane_html = event["lane_html"]
        await self.safe_send(
            json.dumps({"type": "rclane.update", "lane_html": lane_html})
        )


class ChangeDriverConsumer(SafeSendMixin, AsyncWebsocketConsumer):
    async def connect(self):
        self.driverc_group_name = "changedriver"

        await self.channel_layer.group_add(self.driverc_group_name, self.channel_name)
        await self.accept()

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard(
            self.driverc_group_name, self.channel_name
        )

    async def changedriver_update(self, event):
        driverc_html = event["driverc_html"]
        await self.safe_send(json.dumps({"driverc_html": driverc_html}))


class RoundConsumer(SafeSendMixin, AsyncWebsocketConsumer):
    async def connect(self):
        _log.info("Round Consumer connection")
        self.round_id = self.scope["url_route"]["kwargs"]["round_id"]
        self.round_group_name = f"round_{self.round_id}"

        # Join room group
        await self.channel_layer.group_add(self.round_group_name, self.channel_name)

        await self.accept()
        _log.info(f"Round Consumer connection to {self.round_group_name} accepted.")

    async def disconnect(self, close_code):
        # Leave room group
        await self.channel_layer.group_discard(self.round_group_name, self.channel_name)

    async def receive(self, text_data):
        """Handle client requests — supports resync on tab focus."""
        try:
            data = json.loads(text_data)
            if data.get("type") == "resync":
                payload = await self._get_round_state()
                if payload:
                    await self.safe_send(json.dumps(payload))
        except json.JSONDecodeError:
            pass

    @database_sync_to_async
    def _get_round_state(self):
        """Build current round state for resync."""
        from .signals import _build_round_update_payload

        try:
            cround = Round.objects.get(id=self.round_id)
        except Round.DoesNotExist:
            return None
        payload = _build_round_update_payload(cround)
        return {
            "is_paused": payload["is paused"],
            "remaining_seconds": payload["remaining seconds"],
            "session_update": False,
            "started": payload["started"],
            "ready": payload["ready"],
            "ended": payload["ended"],
            "armed": payload.get("armed", False),
            "start_mode": payload.get("start_mode"),
            "active_race_type": payload.get("active_race_type"),
            "active_race_label": payload.get("active_race_label"),
            "has_more_races": payload.get("has_more_races"),
        }

    # Receive message from room group
    async def round_update(self, event):
        # Send message to WebSocket
        await self.safe_send(
            json.dumps(
                {
                    "is_paused": event["is paused"],
                    "remaining_seconds": event["remaining seconds"],
                    "session_update": False,
                    "started": event["started"],
                    "ready": event["ready"],
                    "ended": event["ended"],
                    "armed": event.get("armed", False),
                    "start_mode": event.get("start_mode"),
                    "active_race_type": event.get("active_race_type"),
                    "active_race_label": event.get("active_race_label"),
                    "has_more_races": event.get("has_more_races"),
                    "race_ready": event.get("race_ready", False),
                }
            )
        )

    # Receive message from room group
    async def session_update(self, event):
        # Send message to WebSocket
        await self.safe_send(
            json.dumps(
                {
                    "is_paused": event["is paused"],
                    "time_spent": event["time spent"],
                    "session_update": True,
                    "driver_id": event["driver id"],
                    "driver_status": event["driver status"],
                    "completed_sessions": event["completed sessions"],
                    "team_number": event.get("team number"),
                }
            )
        )

    async def pause_update(self, event):
        # Send message to WebSocket
        await self.safe_send(
            json.dumps(
                {
                    "session_update": False,
                    "is_paused": event["is paused"],
                    "remaining_seconds": event["remaining seconds"],
                    "started": event["started"],
                    "ready": event["ready"],
                    "ended": event["ended"],
                    "armed": event.get("armed", False),
                    "start_mode": event.get("start_mode"),
                    "active_race_type": event.get("active_race_type"),
                    "active_race_label": event.get("active_race_label"),
                    "has_more_races": event.get("has_more_races"),
                }
            )
        )

    async def grid_violation(self, event):
        await self.safe_send(
            json.dumps(
                {
                    "type": "grid_violation",
                    "team_number": event["team_number"],
                    "team_name": event["team_name"],
                    "expected_position": event["expected_position"],
                    "actual_position": event["actual_position"],
                }
            )
        )

    async def race_lap_update(self, event):
        """Broadcast lap crossing updates to race control"""
        msg = {
            "type": "race_lap_update",
            "race_id": event["race_id"],
            "team_number": event["team_number"],
            "lap_number": event["lap_number"],
            "lap_time": event.get("lap_time"),
            "is_suspicious": event.get("is_suspicious", False),
            "suggested_split": event.get("suggested_split", 2),
            "max_split": event.get("max_split", 2),
            "crossing_id": event.get("crossing_id"),
        }
        if event.get("remaining_seconds") is not None:
            msg["remaining_seconds"] = event["remaining_seconds"]
        await self.safe_send(json.dumps(msg))

    async def race_finished(self, event):
        """Broadcast race finished notification to race control"""
        await self.safe_send(
            json.dumps(
                {
                    "type": "race_finished",
                    "race_id": event["race_id"],
                    "race_type": event["race_type"],
                }
            )
        )


class StopAndGoConsumer(SafeSendMixin, AsyncWebsocketConsumer):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Get HMAC secret from settings or use default
        self.hmac_secret = getattr(
            settings, "STOPANDGO_HMAC_SECRET", "race_control_hmac_key_2024"
        ).encode("utf-8")

    def sign_message(self, message_data):
        """Sign outgoing message with HMAC"""
        message_str = json.dumps(message_data, sort_keys=False, separators=(",", ":"))
        signature = hmac.new(
            self.hmac_secret,
            message_str.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        message_data["hmac_signature"] = signature
        return message_data

    def verify_hmac(self, message_data, provided_signature):
        """Verify HMAC signature for incoming message"""
        message_str = json.dumps(message_data, sort_keys=False, separators=(",", ":"))
        expected_signature = hmac.new(
            self.hmac_secret,
            message_str.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        return hmac.compare_digest(expected_signature, provided_signature)

    async def connect(self):
        self.stopandgo_group_name = "stopandgo"

        # Join room group
        await self.channel_layer.group_add(self.stopandgo_group_name, self.channel_name)
        await self.accept()
        _log.info("Stop and Go station connected")

    async def disconnect(self, close_code):
        # Leave room group
        await self.channel_layer.group_discard(
            self.stopandgo_group_name, self.channel_name
        )
        _log.info("Stop and Go station disconnected")

    async def receive(self, text_data):
        try:
            data = json.loads(text_data)

            # Verify HMAC signature for all incoming messages
            provided_signature = data.pop("hmac_signature", None)
            if not provided_signature:
                _log.warning("Received message without HMAC signature")
                return

            if not self.verify_hmac(data, provided_signature):
                _log.warning("HMAC verification failed - rejecting message")
                return

            # Handle both race control commands and station responses
            message_type = data.get("type")

            if message_type == "response":
                # Handle station responses
                response_type = data.get("response")

                if response_type == "penalty_served":
                    team_number = data.get("team")
                    if team_number:
                        _log.info(f"Penalty served by team {team_number}")

                        # Send signed acknowledgment back to station
                        message = {
                            "type": "penalty_acknowledged",
                            "team": team_number,
                            "timestamp": dt.datetime.now().isoformat(),
                        }
                        signed_message = self.sign_message(message)
                        await self.safe_send(json.dumps(signed_message))

                        # Mark penalty as served in database and handle queue
                        await self.handle_penalty_served_from_station(team_number)

                        # Broadcast penalty served to race control
                        await self.channel_layer.group_send(
                            self.stopandgo_group_name,
                            {
                                "type": "penalty_served",
                                "team": team_number,
                            },
                        )

                elif response_type == "fence_status":
                    # Forward fence status to race control
                    await self.channel_layer.group_send(
                        self.stopandgo_group_name,
                        {"type": "fence_status", "enabled": data.get("enabled", True)},
                    )

                elif response_type == "penalty_completed":
                    team_number = data.get("team")
                    if team_number:
                        _log.info(f"Penalty force completed for team {team_number}")
                        await self.channel_layer.group_send(
                            self.stopandgo_group_name,
                            {"type": "penalty_completed", "team": team_number},
                        )
            elif message_type == "penalty_acknowledged":
                # Handle penalty acknowledgment from race control
                team_number = data.get("team")
                if team_number:
                    _log.info(
                        f"Race control acknowledged penalty for team {team_number}"
                    )
                    # Send penalty_acknowledged message to station (not as command)
                    message = {
                        "type": "penalty_acknowledged",
                        "team": team_number,
                        "timestamp": dt.datetime.now().isoformat(),
                    }
                    signed_message = self.sign_message(message)
                    await self.safe_send(json.dumps(signed_message))
            else:
                # Handle race control commands
                if message_type == "penalty_required":
                    # Forward race command to station
                    team = data.get("team")
                    duration = data.get("duration")
                    if team and duration:
                        await self.channel_layer.group_send(
                            self.stopandgo_group_name,
                            {
                                "type": "penalty_required",
                                "team": team,
                                "duration": duration,
                            },
                        )
                elif message_type == "get_fence_status":
                    # Query fence status
                    await self.channel_layer.group_send(
                        self.stopandgo_group_name, {"type": "get_fence_status"}
                    )
                elif message_type == "set_fence":
                    # Set fence status
                    enabled = data.get("enabled")
                    if enabled is not None:
                        await self.channel_layer.group_send(
                            self.stopandgo_group_name,
                            {"type": "set_fence", "enabled": enabled},
                        )
                elif message_type == "force_complete_penalty":
                    # Force complete penalty
                    await self.channel_layer.group_send(
                        self.stopandgo_group_name, {"type": "force_complete_penalty"}
                    )

        except json.JSONDecodeError:
            _log.warning("Invalid JSON received from stop and go connection")

    async def penalty_required(self, event):
        # Send signed penalty required command to station
        message = {
            "type": "command",
            "command": "penalty_required",
            "team": event["team"],
            "duration": event["duration"],
            "timestamp": dt.datetime.now().isoformat(),
        }
        signed_message = self.sign_message(message)
        await self.safe_send(json.dumps(signed_message))

    async def set_fence(self, event):
        # Send signed fence enable/disable command to station
        message = {
            "type": "command",
            "command": "set_fence",
            "enabled": event["enabled"],
            "timestamp": dt.datetime.now().isoformat(),
        }
        signed_message = self.sign_message(message)
        await self.safe_send(json.dumps(signed_message))

    async def get_fence_status(self, event):
        # Send signed query for fence status from station
        message = {
            "type": "command",
            "command": "get_fence_status",
            "timestamp": dt.datetime.now().isoformat(),
        }
        signed_message = self.sign_message(message)
        await self.safe_send(json.dumps(signed_message))

    async def force_complete_penalty(self, event):
        # Send signed force complete penalty command to station
        message = {
            "type": "command",
            "command": "force_complete",
            "timestamp": dt.datetime.now().isoformat(),
        }
        signed_message = self.sign_message(message)
        await self.safe_send(json.dumps(signed_message))

    async def penalty_served(self, event):
        # Broadcast penalty served notification to race control interfaces
        await self.safe_send(
            json.dumps({"type": "penalty_served", "team": event["team"]})
        )

    async def fence_status(self, event):
        # Broadcast fence status to race control interfaces
        await self.safe_send(
            json.dumps({"type": "fence_status", "enabled": event["enabled"]})
        )

    async def penalty_completed(self, event):
        # Broadcast penalty completion notification to race control interfaces
        await self.safe_send(
            json.dumps({"type": "penalty_completed", "team": event["team"]})
        )

    async def penalty_queue_update(self, event):
        # Broadcast penalty queue status update to race control interfaces
        await self.safe_send(
            json.dumps(
                {
                    "type": "penalty_queue_update",
                    "serving_team": event["serving_team"],
                    "queue_count": event["queue_count"],
                    "crossings_since_queued": event.get("crossings_since_queued", 0),
                    "round_id": event["round_id"],
                }
            )
        )

    async def race_lap_update(self, event):
        """Broadcast lap crossing updates to race control"""
        msg = {
            "type": "race_lap_update",
            "race_id": event["race_id"],
            "team_number": event["team_number"],
            "lap_number": event["lap_number"],
            "lap_time": event.get("lap_time"),
            "is_suspicious": event.get("is_suspicious", False),
            "suggested_split": event.get("suggested_split", 2),
            "max_split": event.get("max_split", 2),
            "crossing_id": event.get("crossing_id"),
        }
        if event.get("remaining_seconds") is not None:
            msg["remaining_seconds"] = event["remaining_seconds"]
        await self.safe_send(json.dumps(msg))

    async def race_finished(self, event):
        """Broadcast race finished notification to race control"""
        await self.safe_send(
            json.dumps(
                {
                    "type": "race_finished",
                    "race_id": event["race_id"],
                    "race_type": event["race_type"],
                }
            )
        )

    async def handle_penalty_served_from_station(self, team_number):
        """Handle when station reports a penalty as served"""
        from channels.db import database_sync_to_async
        from .models import PenaltyQueue, RoundPenalty, Round
        import datetime as dt

        try:
            # Find current round
            current_round = await self.get_current_round()
            if not current_round:
                return

            # Find the next penalty in queue for this team that hasn't been served yet
            # Use the queue order to get the first one for this team
            active_penalty = await database_sync_to_async(
                lambda: PenaltyQueue.objects.filter(
                    round_penalty__round=current_round,
                    round_penalty__offender__team__number=team_number,
                    round_penalty__served__isnull=True,
                )
                .order_by("timestamp")
                .first()
            )()

            if active_penalty:
                _log.info(
                    f"Processing station-reported penalty served for team {team_number}"
                )

                penalty_duration = await database_sync_to_async(
                    lambda: active_penalty.round_penalty.value
                )()

                # Mark penalty as served
                await database_sync_to_async(
                    lambda: setattr(
                        active_penalty.round_penalty, "served", dt.datetime.now()
                    )
                )()
                await database_sync_to_async(
                    lambda: active_penalty.round_penalty.save()
                )()

                # Remove from queue
                await database_sync_to_async(lambda: active_penalty.delete())()

                # Reset next penalty's timestamp so crossing count starts fresh
                from .signals import reset_next_penalty_timestamp

                await database_sync_to_async(reset_next_penalty_timestamp)(
                    current_round.id
                )

                # Notify simulator: S&G stop adds penalty_duration + 5 s to current lap
                await self.channel_layer.group_send(
                    "timing",
                    {
                        "type": "timing_team_delay",
                        "team_number": team_number,
                        "extra_seconds": float(penalty_duration) + 5.0,
                    },
                )

                # Trigger next penalty after 10 seconds
                await self.trigger_next_penalty_after_delay(current_round.id)
            else:
                _log.info(
                    f"Ignoring station penalty_served for team {team_number} - penalty already processed or not found"
                )

        except Exception as e:
            _log.error(f"Error handling penalty served from station: {e}")

    @database_sync_to_async
    def get_current_round(self):
        """Get the current active round"""
        from .models import Round
        import datetime as dt
        from django.db.models import Q

        end_date = dt.date.today()
        start_date = end_date - dt.timedelta(days=1)
        return Round.objects.filter(
            Q(start__date__range=[start_date, end_date]) & Q(ended__isnull=True)
        ).first()

    async def trigger_next_penalty_after_delay(self, round_id):
        """Trigger next penalty in queue after 10 second delay"""
        import asyncio

        # Wait 10 seconds for station to clear
        await asyncio.sleep(10)

        # Get next penalty in queue with all related data
        penalty_data = await self.get_next_penalty_data(round_id)

        if penalty_data:
            # Signal the stop and go station for next penalty
            await self.channel_layer.group_send(
                self.stopandgo_group_name,
                {
                    "type": "penalty_required",
                    "team": penalty_data["team_number"],
                    "duration": penalty_data["duration"],
                    "penalty_id": penalty_data["penalty_id"],
                },
            )
            _log.info(f"Triggered next penalty for team {penalty_data['team_number']}")

    @database_sync_to_async
    def get_next_penalty_data(self, round_id):
        """Get next penalty data with all relationships resolved"""
        from .models import PenaltyQueue

        next_penalty = PenaltyQueue.get_next_penalty(round_id)

        if next_penalty:
            return {
                "team_number": next_penalty.round_penalty.offender.team.number,
                "duration": next_penalty.round_penalty.value,
                "penalty_id": next_penalty.round_penalty.id,
            }
        return None

    async def handle_penalty_state_change(self, round_id):
        """Handle penalty state changes from race control (cancel/delay)"""
        # Trigger next penalty after 10 second delay
        await self.trigger_next_penalty_after_delay(round_id)

    # Add handlers for penalty state changes from race control
    async def penalty_cancelled(self, event):
        """Handle penalty cancellation from race control"""
        round_id = event.get("round_id")
        if round_id:
            await self.handle_penalty_state_change(round_id)

    async def penalty_delayed(self, event):
        """Handle penalty delay from race control"""
        round_id = event.get("round_id")
        if round_id:
            await self.handle_penalty_state_change(round_id)

    async def reset_station(self, event):
        """Send reset command to stop and go station"""
        message = {
            "type": "command",
            "command": "reset",
            "timestamp": dt.datetime.now().isoformat(),
        }
        signed_message = self.sign_message(message)
        await self.safe_send(json.dumps(signed_message))


# Signal handler for race end requests - placed outside classes
from django.dispatch import receiver
from asgiref.sync import sync_to_async
from .signals import race_end_requested


@receiver(race_end_requested)
async def handle_race_end_request(sender, round_id, **kwargs):
    """
    Handle race end requests with proper async locking.
    This ensures only one end_race operation can run at a time per round.
    """
    _log.info(f"Race end requested for Round {round_id}")

    try:
        # Get the round instance
        round_instance = await Round.objects.aget(id=round_id)

        # Use the round's instance-level lock for thread safety
        async with round_instance._end_race_lock:
            if not round_instance.ended:
                _log.info(f"Ending race {round_id} with lock protection")
                await sync_to_async(round_instance.end_race)()
                _log.info(f"Race {round_id} ended successfully")
            else:
                _log.info(f"Race {round_id} already ended - skipping")

    except Exception as e:
        _log.error(f"Error ending race {round_id}: {e}")


class TimingConsumer(SafeSendMixin, AsyncWebsocketConsumer):
    """
    WebSocket consumer for timing daemon communication.

    Handles lap crossing events from timing hardware via daemon.
    Calculates lap times from raw_time based on configured timing mode.
    Sends ACK per message_id for at-least-once delivery.
    """

    VALID_TIMING_MODES = {"interval", "duration", "time_of_day", "own_time"}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.hmac_secret = getattr(
            settings, "TIMING_HMAC_SECRET", "timing_hmac_secret_change_me_2025"
        ).encode("utf-8")
        self._station_connected = False
        self._timing_mode = None
        self._rollover_seconds = 360000.0

    def sign_message(self, message_data):
        """Sign outgoing message with HMAC"""
        message_str = json.dumps(message_data, sort_keys=False, separators=(",", ":"))
        signature = hmac.new(
            self.hmac_secret,
            message_str.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        message_data["hmac_signature"] = signature
        return message_data

    def verify_hmac(self, message_data, provided_signature):
        """Verify HMAC signature for incoming message"""
        message_str = json.dumps(message_data, sort_keys=False, separators=(",", ":"))
        expected_signature = hmac.new(
            self.hmac_secret,
            message_str.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        return hmac.compare_digest(expected_signature, provided_signature)

    async def connect(self):
        self.timing_group_name = "timing"

        await self.channel_layer.group_add(self.timing_group_name, self.channel_name)
        await self.accept()
        _log.info("Timing daemon connected")

    async def disconnect(self, close_code):
        self._station_connected = False
        await self.channel_layer.group_discard(
            self.timing_group_name, self.channel_name
        )
        _log.info("Timing daemon disconnected")

    async def receive(self, text_data):
        try:
            data = json.loads(text_data)

            provided_signature = data.pop("hmac_signature", None)
            if not provided_signature:
                _log.warning("Timing: Received message without HMAC signature")
                return

            if not self.verify_hmac(data, provided_signature):
                _log.warning("Timing: HMAC verification failed - rejecting message")
                return

            message_type = data.get("type")

            if message_type == "connected":
                timing_mode = data.get("timing_mode", "duration")
                if timing_mode not in self.VALID_TIMING_MODES:
                    _log.warning(
                        f"Timing: Invalid timing_mode '{timing_mode}', rejecting"
                    )
                    return
                self._timing_mode = timing_mode
                self._rollover_seconds = float(data.get("rollover_seconds", 360000.0))
                self._station_connected = True
                _log.info(
                    f"Timing station connected: plugin={data.get('plugin_type')} "
                    f"mode={self._timing_mode} rollover={self._rollover_seconds}"
                )

            elif message_type == "lap_crossing":
                if not self._station_connected:
                    _log.warning(
                        "Timing: lap_crossing before connected message, ignoring"
                    )
                    return
                # Broadcast raw transponder detection for scan listeners
                await self.channel_layer.group_send(
                    "transponder_scan",
                    {
                        "type": "transponder_detected",
                        "transponder_id": data.get("transponder_id"),
                        "timestamp": data.get("timestamp"),
                    },
                )
                result = await self.handle_lap_crossing(data)
                # Send ACK and broadcasts from async context (not from thread pool)
                message_id = data.get("message_id")
                if message_id:
                    await self.send_ack(message_id)
                if result:
                    await self._broadcast_crossing(result)

            elif message_type == "warning":
                _log.debug(f"Timing warning: {data.get('message')}")

            elif message_type == "response":
                _log.debug(f"Timing response: {data.get('response')}")

        except json.JSONDecodeError:
            _log.warning("Timing: Invalid JSON received")
        except Exception as e:
            _log.error(f"Timing: Error processing message: {e}")

    async def send_ack(self, message_id):
        """Send ACK for a processed crossing back to the station."""
        message = {"type": "ack", "message_id": message_id}
        signed = self.sign_message(message)
        await self.safe_send(json.dumps(signed))

    async def timing_race_started(self, event):
        """Forward race_started channel-layer event to the connected timing station."""
        command = {
            "type": "command",
            "command": "race_started",
            "race_id": event["race_id"],
            "round_id": event["round_id"],
            "assignments": event["assignments"],
        }
        await self.safe_send(json.dumps(self.sign_message(command)))
        # Schedule server-side auto-end for time-only modes (QUALIFYING, etc.)
        asyncio.ensure_future(self._schedule_auto_end(event["race_id"]))

    async def timing_team_delay(self, event):
        """Forward team_delay event to the connected timing station."""
        command = {
            "type": "command",
            "command": "team_delay",
            "team_number": event["team_number"],
            "extra_seconds": event["extra_seconds"],
            "skip_crossing": event.get("skip_crossing", False),
        }
        await self.safe_send(json.dumps(self.sign_message(command)))

    async def _broadcast_crossing(self, result):
        """Broadcast crossing data to leaderboard and race control groups."""
        race_id = result["race_id"]
        round_id = result["round_id"]
        team_number = result["team_number"]
        lap_number = result["lap_number"]
        lap_time = result["lap_time"]
        is_suspicious = result["is_suspicious"]
        suggested_split = result.get("suggested_split", 1)
        max_split = result.get("max_split", 1)

        await self.channel_layer.group_send(
            f"leaderboard_{race_id}",
            {
                "type": "lap_crossing_update",
                "crossing_data": {
                    "team_number": team_number,
                    "lap_number": lap_number,
                    "lap_time": str(lap_time) if lap_time else None,
                },
            },
        )

        await self.channel_layer.group_send(
            f"round_{round_id}",
            {
                "type": "race_lap_update",
                "race_id": race_id,
                "team_number": team_number,
                "lap_number": lap_number,
                "lap_time": str(lap_time) if lap_time else None,
                "is_suspicious": is_suspicious,
                "suggested_split": suggested_split,
                "max_split": max_split,
                "crossing_id": result.get("crossing_id"),
                "remaining_seconds": result.get("remaining_seconds"),
            },
        )

        if result.get("grid_violation"):
            await self.channel_layer.group_send(
                f"round_{round_id}",
                {"type": "grid_violation", **result["grid_violation"]},
            )

        # Update penalty queue crossing count when penalties are queued
        from .signals import send_penalty_queue_update

        has_queue = await database_sync_to_async(
            lambda: PenaltyQueue.objects.filter(
                round_penalty__round_id=round_id
            ).exists()
        )()
        if has_queue:
            await database_sync_to_async(send_penalty_queue_update)(round_id)

        if result.get("race_started"):
            # FIRST_CROSSING mode: race just started on this crossing — schedule auto-end
            asyncio.ensure_future(self._schedule_auto_end(race_id))

        if result.get("race_finished"):
            _log.info(f"Race {race_id} finished!")
            await self.channel_layer.group_send(
                f"round_{round_id}",
                {
                    "type": "race_finished",
                    "race_id": race_id,
                    "race_type": result["race_type"],
                },
            )
            # Tell the timing station so SimulatorPlugin can wind down
            await self.safe_send(
                json.dumps(
                    self.sign_message(
                        {"type": "command", "command": "race_ended", "race_id": race_id}
                    )
                )
            )

    async def _schedule_auto_end(self, race_id):
        """Sleep until the race time limit expires then auto-end the race."""
        _AUTO_END_MODES = ("QUALIFYING", "TIME_ONLY")
        delay = await database_sync_to_async(self._get_auto_end_delay)(
            race_id, _AUTO_END_MODES
        )
        if delay is None:
            return
        _log.info(f"Race {race_id}: auto-end scheduled in {delay:.1f}s")
        await asyncio.sleep(delay)
        ended = await database_sync_to_async(self._do_auto_end_race)(race_id)
        if ended:
            _log.info(f"Race {race_id}: auto-ended after time limit")

    @staticmethod
    def _get_auto_end_delay(race_id, modes):
        """Return seconds remaining until race time limit, or None if not applicable."""
        from .models import Race as _Race

        try:
            race = _Race.objects.select_related("round", "round__championship").get(
                id=race_id
            )
        except _Race.DoesNotExist:
            return None
        if race.ending_mode not in modes or not race.started or race.ended:
            return None
        elapsed = (dt.datetime.now() - race.started).total_seconds()
        limit = race.get_effective_time_limit().total_seconds()
        return max(0.0, limit - elapsed)

    @staticmethod
    def _do_auto_end_race(race_id):
        """End race if time has expired and it's still running. Returns True if ended."""
        from .models import Race as _Race

        try:
            race = _Race.objects.select_related("round", "round__championship").get(
                id=race_id, ended__isnull=True
            )
        except _Race.DoesNotExist:
            return False
        if race.is_race_finished():
            race.end_this_race()
            return True
        return False

    def _calculate_lap_time(self, raw_time, previous_raw_time):
        """
        Calculate lap time from raw decoder values based on timing mode.

        Returns dt.timedelta or None.
        """
        if previous_raw_time is None:
            if self._timing_mode == "interval":
                # First passage in interval mode: raw_time should be 0
                return None
            # For other modes, first passage has no previous -> no lap time
            return None

        if self._timing_mode == "interval":
            # raw_time IS the lap time
            return dt.timedelta(seconds=raw_time)

        # duration / time_of_day / own_time: delta between consecutive raw values
        delta = raw_time - previous_raw_time

        if delta < 0:
            if self._timing_mode == "time_of_day":
                delta += 86400.0
            elif self._timing_mode == "own_time":
                delta += self._rollover_seconds
            # duration mode: negative delta is genuinely invalid (shouldn't happen)

        if delta <= 0:
            return None

        return dt.timedelta(seconds=delta)

    @database_sync_to_async
    def handle_lap_crossing(self, data):
        """
        Process lap crossing event and create LapCrossing record.

        Returns a result dict for broadcasting, or None if the crossing
        was skipped (unknown transponder, no assignment, duplicate).
        """
        try:
            transponder_id = data.get("transponder_id")
            timestamp_str = data.get("timestamp")
            raw_time = data.get("raw_time")
            message_id = data.get("message_id")

            # Parse timestamp
            crossing_time = dt.datetime.fromisoformat(timestamp_str)

            # Deduplicate by message_id
            if message_id:
                try:
                    msg_uuid = uuid.UUID(message_id)
                except ValueError:
                    msg_uuid = None
                if (
                    msg_uuid
                    and LapCrossing.objects.filter(message_id=msg_uuid).exists()
                ):
                    _log.debug(
                        f"Timing: Duplicate message_id {message_id[:8]}, skipping"
                    )
                    return None
            else:
                msg_uuid = None

            # Get transponder
            transponder = Transponder.objects.filter(
                transponder_id=transponder_id
            ).first()

            if not transponder:
                _log.debug(f"Timing: Unknown transponder {transponder_id}")
                return None

            # Update transponder last_seen
            transponder.last_seen = crossing_time
            transponder.save(update_fields=["last_seen"])

            # Find active race assignment
            assignment = (
                RaceTransponderAssignment.objects.filter(
                    transponder=transponder,
                    race__round__started__isnull=False,
                    race__round__ended__isnull=True,
                    race__ended__isnull=True,
                )
                .select_related("race", "race__round", "team", "team__team")
                .first()
            )

            if not assignment:
                _log.debug(
                    f"Timing: No active race assignment for transponder {transponder_id}"
                )
                return None

            race = assignment.race
            team = assignment.team

            # Drop crossings for races that haven't been armed or started yet.
            # This prevents karts still on track after Q2 ends from accidentally
            # triggering the Main Race start via FIRST_CROSSING mode.
            race_accepts_crossing = race.started is not None or (
                race.ready and race.start_mode != "IMMEDIATE"
            )
            if not race_accepts_crossing:
                _log.debug(
                    f"Timing: Race {race.race_type} not armed/started — "
                    f"dropping crossing for team {team.number}"
                )
                return None

            # Drop crossings once the race is over (manual RD end or auto-end).
            # This freezes positions at the moment the race ended — equivalent to
            # the race director pressing "End Race" which behaves as mode 1.
            if race.ended is not None:
                _log.debug(
                    f"Timing: Race {race.race_type} already ended — "
                    f"dropping crossing for team {team.number}"
                )
                return None

            # Dedup: if this team already had a crossing within TRANSPONDER_DEDUP_SECONDS,
            # this is a redundant transponder on the same kart — drop it silently.
            TRANSPONDER_DEDUP_SECONDS = 7
            if LapCrossing.objects.filter(
                race=race,
                team=team,
                crossing_time__gt=crossing_time
                - dt.timedelta(seconds=TRANSPONDER_DEDUP_SECONDS),
                crossing_time__lte=crossing_time,
            ).exists():
                _log.debug(
                    f"Timing: Transponder dedup — team {team.number} "
                    f"already crossed within {TRANSPONDER_DEDUP_SECONDS}s, skipping"
                )
                return None

            # Post-expiry logic: once a team has made their "finishing crossing"
            # (first crossing at or after the finish_boundary), all subsequent
            # crossings for that team are dropped.
            #
            # finish_boundary varies by mode:
            #   CROSS_AFTER_TIME / QUALIFYING_PLUS / AUTO_TRANSFORM → cutoff_time
            #   CROSS_AFTER_LEADER → leader's first post-cutoff crossing time
            #     (None until the leader crosses, so pre-leader crossings are
            #      recorded as normal laps without triggering the finishing logic)
            _TIME_FINISH_MODES = (
                "CROSS_AFTER_TIME",
                "QUALIFYING_PLUS",
                "AUTO_TRANSFORM",
            )
            cutoff_time = None
            if (
                race.ending_mode in _TIME_FINISH_MODES + ("CROSS_AFTER_LEADER",)
                and race.started
            ):
                cutoff_time = race.started + race.get_effective_time_limit()

            finish_boundary = None
            if cutoff_time is not None:
                if race.ending_mode in _TIME_FINISH_MODES:
                    finish_boundary = cutoff_time
                elif (
                    race.ending_mode == "CROSS_AFTER_LEADER"
                    and crossing_time >= cutoff_time
                ):
                    finish_boundary = race.get_leader_finish_time(cutoff_time)
                    # None until leader crosses — pre-leader post-cutoff laps are kept

            if finish_boundary is not None and crossing_time >= finish_boundary:
                already_finished = LapCrossing.objects.filter(
                    race=race, team=team, crossing_time__gte=finish_boundary
                ).exists()
                if already_finished:
                    _log.debug(
                        f"Timing: Post-expiry crossing for team {team.number} "
                        f"({race.race_type}/{race.ending_mode}) — already has "
                        f"finishing crossing, dropping"
                    )
                    return None

            # Get last crossing for this team (for lap number and raw_time reference)
            last_crossing = (
                LapCrossing.objects.filter(race=race, team=team, is_valid=True)
                .order_by("-lap_number")
                .first()
            )

            lap_number = (last_crossing.lap_number + 1) if last_crossing else 0

            # Calculate lap time from raw_time using timing mode
            previous_raw = last_crossing.raw_time if last_crossing else None
            lap_time = self._calculate_lap_time(raw_time, previous_raw)

            # Check if race is suspended
            is_suspended = race.round.is_paused
            should_count = True
            if is_suspended and not race.count_crossings_during_suspension:
                should_count = False

            # Create lap crossing
            crossing = LapCrossing.objects.create(
                race=race,
                team=team,
                transponder=transponder,
                lap_number=lap_number,
                crossing_time=crossing_time,
                lap_time=lap_time,
                raw_time=raw_time,
                message_id=msg_uuid,
                is_valid=should_count,
                counted_during_suspension=is_suspended,
            )

            team_number = team.team.number

            # Check for suspicious lap time
            suggested_split = 1
            max_split = 1
            is_suspicious = False
            if lap_time and should_count:
                suggested_split, max_split = self.estimate_lap_count(
                    race, lap_time, team, crossing_time
                )
                if suggested_split > 1:
                    is_suspicious = True

                    # Check if this is a pit-bypass suspicious lap (driver change
                    # happened during this lap window)
                    cround = race.round
                    pit_change = False
                    if cround.auto_handle_pit_suspicious:
                        window_start = crossing_time - lap_time
                        pit_change = Session.objects.filter(
                            driver__team=team,
                            race=race,
                            end__gte=window_start,
                            end__lte=crossing_time,
                        ).exists()

                    if pit_change:
                        action = cround.pit_suspicious_action
                        if action == "dismiss":
                            is_suspicious = False
                            _log.warning(
                                f"Auto-dismissed pit suspicious lap: Team {team_number}, "
                                f"Lap {lap_number}, Time {lap_time}"
                            )
                        elif action == "split":
                            # Auto-split: create evenly-spaced laps
                            count = suggested_split
                            prev = (
                                LapCrossing.objects.filter(
                                    race=race,
                                    team=team,
                                    lap_number__lt=lap_number,
                                )
                                .order_by("-lap_number")
                                .first()
                            )
                            if prev:
                                time_delta = crossing_time - prev.crossing_time
                                slice_dur = time_delta / count
                                # Shift subsequent laps
                                LapCrossing.objects.filter(
                                    race=race,
                                    team=team,
                                    lap_number__gt=lap_number,
                                ).update(lap_number=F("lap_number") + (count - 1))
                                # Create split laps
                                for i in range(count):
                                    ct = (
                                        prev.crossing_time + slice_dur * (i + 1)
                                        if i < count - 1
                                        else crossing_time
                                    )
                                    LapCrossing.objects.create(
                                        race=race,
                                        team=team,
                                        transponder=crossing.transponder,
                                        lap_number=lap_number + i,
                                        crossing_time=ct,
                                        lap_time=slice_dur,
                                        is_valid=True,
                                        is_suspicious=False,
                                        was_split=True,
                                        split_from=crossing,
                                        counted_during_suspension=crossing.counted_during_suspension,
                                        session=crossing.session,
                                    )
                                # Mark original as invalid
                                crossing.is_valid = False
                                crossing.save()
                                is_suspicious = False
                                # Update lap_number for broadcast
                                lap_number = lap_number + count - 1
                                _log.warning(
                                    f"Auto-split pit suspicious lap: Team {team_number}, "
                                    f"into {count} laps"
                                )
                    else:
                        crossing.is_suspicious = True
                        crossing.save(update_fields=["is_suspicious"])
                        _log.warning(
                            f"Suspicious lap: Team {team_number}, "
                            f"Lap {lap_number}, Time {lap_time}, "
                            f"suggested split: {suggested_split}, max: {max_split}"
                        )

            _log.info(
                f"Lap recorded: Team {team_number}, Lap {lap_number}, "
                f"Time: {lap_time}, raw={raw_time}"
            )

            # Trigger Race.started on first crossing (FIRST_CROSSING mode)
            race_started = False
            if (
                lap_number == 0
                and race.started is None
                and race.start_mode != "IMMEDIATE"
            ):
                race.started = crossing_time
                race.save(update_fields=["started"])
                race_started = True
                # Adjust all open sessions to start at race start time so that
                # pre-race warm-up time (before first crossing) is not counted.
                for session in Session.objects.filter(
                    race=race, start__isnull=False, end__isnull=True
                ):
                    session.start = crossing_time
                    session.save(update_fields=["start"])

            # For CROSS_AFTER_LEADER: the finish_boundary is derived from
            # get_leader_finish_time() which queries saved crossings.  When
            # THIS crossing is the leader's first post-cutoff crossing it
            # wasn't in the DB yet at query time, so finish_boundary was None.
            # Now that the crossing is saved, re-evaluate.
            if (
                finish_boundary is None
                and race.ending_mode == "CROSS_AFTER_LEADER"
                and cutoff_time is not None
                and crossing_time >= cutoff_time
            ):
                finish_boundary = race.get_leader_finish_time(cutoff_time)

            # Close this team's active session when their finishing crossing is
            # recorded — each team's race ends at their own crossing time, not
            # when the last team eventually triggers end_this_race().
            if finish_boundary is not None and crossing_time >= finish_boundary:
                for session in Session.objects.filter(
                    driver__team=team,
                    race=race,
                    start__isnull=False,
                    end__isnull=True,
                ):
                    session.end = crossing_time
                    session.save()

            # Time-limit race end: triggered by crossings, not by a timer.
            # The race ends once every non-retired team has made their finishing
            # crossing (at or after finish_boundary).
            race_finished = False
            if (
                finish_boundary is not None
                and crossing_time >= finish_boundary
                and not race.ended
            ):
                active_team_ids = set(
                    race.round.round_team_set.filter(retired=False).values_list(
                        "id", flat=True
                    )
                )
                crossed_after_ids = set(
                    LapCrossing.objects.filter(
                        race=race, crossing_time__gte=finish_boundary
                    ).values_list("team_id", flat=True)
                )
                if active_team_ids.issubset(crossed_after_ids):
                    race.end_this_race()
                    race_finished = True

            if not race_finished:
                race_finished = race.is_race_finished()
                # For any mode (lap-based, time-only, timeout), officially end the
                # race so subsequent crossings are dropped and standings are frozen.
                if race_finished and not race.ended:
                    race.end_this_race()

            # Compute server-authoritative remaining time for client clock sync
            if race.started and not race.ended:
                remaining_seconds = max(
                    0, round((race.duration - race.time_elapsed).total_seconds())
                )
            else:
                remaining_seconds = None

            result = {
                "race_id": race.id,
                "round_id": race.round.id,
                "team_number": team_number,
                "lap_number": lap_number,
                "lap_time": lap_time,
                "is_suspicious": is_suspicious,
                "suggested_split": suggested_split if is_suspicious else 1,
                "max_split": max_split if is_suspicious else 1,
                "crossing_id": crossing.id,
                "race_finished": race_finished,
                "race_type": race.race_type if race_finished else None,
                "race_started": race_started,
                "remaining_seconds": remaining_seconds,
            }

            # Grid order check (MAIN race only, driven by ChampionshipPenalty)
            if lap_number == 0 and race.race_type == "MAIN":
                mp_grid = MandatoryPenalty.objects.filter(key="grid_order").first()
                grid_order_penalty = (
                    ChampionshipPenalty.objects.filter(
                        championship=race.round.championship,
                        penalty=mp_grid.penalty,
                    ).first()
                    if mp_grid
                    else None
                )
                if grid_order_penalty:
                    grid_pos = GridPosition.objects.filter(race=race, team=team).first()
                    crossing_order = LapCrossing.objects.filter(
                        race=race, lap_number=0
                    ).count()
                    if grid_pos and crossing_order != grid_pos.position:
                        RoundPenalty.objects.create(
                            round=race.round,
                            offender=team,
                            penalty=grid_order_penalty,
                            value=grid_order_penalty.value,
                            imposed=crossing_time,
                        )
                        result["grid_violation"] = {
                            "team_number": team_number,
                            "team_name": team.team.team.name,
                            "expected_position": grid_pos.position,
                            "actual_position": crossing_order,
                        }

            return result

        except Exception as e:
            _log.error(f"Timing: Error handling lap crossing: {e}")
            return None

    def estimate_lap_count(self, race, lap_time, team=None, crossing_time=None):
        """
        Estimate how many laps a crossing represents.
        Returns (suggested, max) where:
          suggested = round(effective_time / median)
          max       = int(effective_time / median) + 1  (physical upper bound)
        Both are >= 1; suggested >= 2 means suspicious.

        If a penalty was served or a driver change occurred during this lap,
        the extra time is subtracted before computing the ratio.
        """
        try:
            filters = {
                "race": race,
                "is_valid": True,
                "lap_time__isnull": False,
                "is_suspicious": False,
            }
            if team:
                filters["team"] = team

            valid_laps = LapCrossing.objects.filter(**filters)

            if valid_laps.count() < 3:
                return 1, 1

            lap_times = sorted(lap.lap_time.total_seconds() for lap in valid_laps)
            median_time = lap_times[len(lap_times) // 2]

            if median_time <= 0:
                return 1, 1

            lap_secs = lap_time.total_seconds()

            # Build the threshold: 1.9x median + time for known events
            # that legitimately extend this lap
            event_extra = 0.0
            if team and crossing_time:
                window_start = crossing_time - lap_time
                window_end = crossing_time

                # Penalty served during this lap
                served_penalties = RoundPenalty.objects.filter(
                    round=race.round,
                    offender=team,
                    served__gte=window_start,
                    served__lte=window_end,
                )
                for rp in served_penalties:
                    # Penalty duration + 10s for slowdown/speedup
                    event_extra += float(rp.value) + 10.0

                # Driver change during this lap (session ended = old driver out)
                changes = Session.objects.filter(
                    driver__team=team,
                    race=race,
                    end__gte=window_start,
                    end__lte=window_end,
                ).count()
                if changes > 0:
                    event_extra += changes * 30.0

            # Only flag as suspicious if lap exceeds threshold
            threshold = median_time * 1.9 + event_extra
            if lap_secs <= threshold:
                return 1, 1
            # Subtract known event time before estimating lap count
            effective_secs = max(0, lap_secs - event_extra)
            suggested = max(2, round(effective_secs / median_time))
            max_count = int(effective_secs // median_time) + 1
            return suggested, max_count

        except Exception:
            return 1, 1

    async def send_command(self, command_type, **kwargs):
        """Send command to timing daemon"""
        message = {"type": "command", "command": command_type, **kwargs}
        signed = self.sign_message(message)
        await self.safe_send(json.dumps(signed))


class LeaderboardConsumer(SafeSendMixin, AsyncWebsocketConsumer):
    """
    WebSocket consumer for real-time leaderboard updates.
    Broadcasts standings updates when lap crossings occur.
    """

    async def connect(self):
        self.race_id = self.scope["url_route"]["kwargs"]["race_id"]
        self.race_group_name = f"leaderboard_{self.race_id}"

        # Join race leaderboard group
        await self.channel_layer.group_add(self.race_group_name, self.channel_name)

        # Also subscribe to the round group to receive pause/round updates
        try:
            race = await database_sync_to_async(Race.objects.get)(id=self.race_id)
        except Race.DoesNotExist:
            await self.close(code=4404)
            return
        self.round_group_name = f"round_{race.round_id}"
        await self.channel_layer.group_add(self.round_group_name, self.channel_name)

        await self.accept()

        # Send initial standings
        standings, remaining = await self.get_current_standings()
        msg = {"type": "standings_update", "standings": standings}
        if remaining is not None:
            msg["remaining_seconds"] = remaining
        await self.safe_send(json.dumps(msg))

    async def disconnect(self, close_code):
        # Leave race leaderboard group
        await self.channel_layer.group_discard(self.race_group_name, self.channel_name)
        if hasattr(self, "round_group_name"):
            await self.channel_layer.group_discard(
                self.round_group_name, self.channel_name
            )

    async def receive(self, text_data):
        """Handle incoming messages — supports reload requests"""
        try:
            data = json.loads(text_data)
            if data.get("type") == "reload":
                standings, remaining = await self.get_current_standings()
                msg = {"type": "standings_update", "standings": standings}
                if remaining is not None:
                    msg["remaining_seconds"] = remaining
                await self.safe_send(json.dumps(msg))
        except json.JSONDecodeError:
            pass

    async def lap_crossing_update(self, event):
        """
        Called when a lap crossing occurs.
        Recalculate and broadcast standings.
        """
        standings, remaining = await self.get_current_standings()
        msg = {
            "type": "standings_update",
            "standings": standings,
            "flash_team_number": event.get("crossing_data", {}).get("team_number"),
        }
        if remaining is not None:
            msg["remaining_seconds"] = remaining
        await self.safe_send(json.dumps(msg))

    async def race_ended(self, event):
        """Called when pre-race check fires for next race. Redirect this leaderboard."""
        await self.safe_send(
            json.dumps(
                {
                    "type": "race_ended",
                    "next_race_url": event.get("next_race_url"),
                }
            )
        )

    async def pause_update(self, event):
        """Forward pause state changes to the leaderboard client."""
        await self.safe_send(
            json.dumps(
                {
                    "type": "pause_update",
                    "is_paused": event["is paused"],
                    "remaining_seconds": event["remaining seconds"],
                }
            )
        )

    async def race_lap_update(self, event):
        """Lap update sent to the round group — leaderboard gets its own lap_crossing_update."""
        pass

    async def session_update(self, event):
        """Session updates go to the round group — leaderboard doesn't use them."""
        pass

    async def race_finished(self, event):
        """Race-finished notification goes to race control — leaderboard ignores it."""
        pass

    async def grid_violation(self, event):
        """Grid violation goes to race control — leaderboard ignores it."""
        pass

    async def race_standings_refresh(self, event):
        """Push updated standings when race ends (no crossing needed to show flags)."""
        standings, remaining = await self.get_current_standings()
        msg = {"type": "standings_update", "standings": standings}
        if remaining is not None:
            msg["remaining_seconds"] = remaining
        await self.safe_send(json.dumps(msg))

    async def round_update(self, event):
        """Forward round state changes (started, ended) to the leaderboard client."""
        await self.safe_send(
            json.dumps(
                {
                    "type": "round_update",
                    "is_paused": event["is paused"],
                    "remaining_seconds": event["remaining seconds"],
                    "started": event["started"],
                    "ended": event["ended"],
                }
            )
        )

    @database_sync_to_async
    def get_current_standings(self):
        """Get current race standings and remaining time for clock sync."""
        try:
            race = Race.objects.get(id=self.race_id)
            standings = race.calculate_race_standings()
            remaining = None
            if race.started and not race.ended:
                remaining = max(
                    0, round((race.duration - race.time_elapsed).total_seconds())
                )
            return standings, remaining
        except Race.DoesNotExist:
            return [], None


class TransponderScanConsumer(SafeSendMixin, AsyncWebsocketConsumer):
    """
    Read-only WebSocket consumer for transponder scan detection.
    UI pages connect here to auto-detect transponder IDs when a transponder
    passes the timing loop.
    """

    async def connect(self):
        await self.channel_layer.group_add("transponder_scan", self.channel_name)
        await self.accept()

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard("transponder_scan", self.channel_name)

    async def transponder_detected(self, event):
        """Forward transponder detection to WebSocket client."""
        await self.safe_send(
            json.dumps(
                {
                    "type": "transponder_detected",
                    "transponder_id": event["transponder_id"],
                    "timestamp": event["timestamp"],
                }
            )
        )
