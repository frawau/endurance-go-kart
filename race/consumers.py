import asyncio
import json
import time
import uuid
import datetime as dt
import hmac
import hashlib
from django.conf import settings
from channels.generic.websocket import AsyncWebsocketConsumer
from .models import (
    ChangeLane,
    round_team,
    team_member,
    championship_team,
    Round,
    Race,
    Transponder,
    RaceTransponderAssignment,
    LapCrossing,
    GridPosition,
    ChampionshipPenalty,
    RoundPenalty,
)
from django.template.loader import render_to_string
from channels.db import database_sync_to_async
from django.db.models import Count, Q

# Import your models


class EmptyTeamsConsumer(AsyncWebsocketConsumer):
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
        await self.send(
            text_data=json.dumps({"type": "empty_teams_list", "teams": empty_teams})
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
                        "message": "Team deleted successfully"
                        if success
                        else "Failed to delete team",
                        "tag": "success" if success else "danger",
                    },
                )

                # No need to broadcast empty teams list here
                # The signal handlers will automatically do it

    # Receive message from room group
    async def empty_teams_list(self, event):
        # Send teams list to WebSocket
        await self.send(
            text_data=json.dumps({"type": "empty_teams_list", "teams": event["teams"]})
        )

    # Send system message
    async def system_message(self, event):
        # Send message to WebSocket
        await self.send(
            text_data=json.dumps(
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


class ChangeLaneConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.lane_number = self.scope["url_route"]["kwargs"]["pitlane_number"]
        self.lane_group_name = f"lane_{self.lane_number}"

        await self.channel_layer.group_add(self.lane_group_name, self.channel_name)
        await self.accept()

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard(self.lane_group_name, self.channel_name)

    async def lane_update(self, event):
        lane_html = event["lane_html"]
        await self.send(
            text_data=json.dumps({"type": "lane.update", "lane_html": lane_html})
        )

    async def rclane_update(self, event):
        lane_html = event["lane_html"]
        await self.send(
            text_data=json.dumps({"type": "rclane.update", "lane_html": lane_html})
        )


class ChangeDriverConsumer(AsyncWebsocketConsumer):
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
        await self.send(text_data=json.dumps({"driverc_html": driverc_html}))


class RoundConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        print("Round Consumer connection")
        self.round_id = self.scope["url_route"]["kwargs"]["round_id"]
        self.round_group_name = f"round_{self.round_id}"

        # Join room group
        await self.channel_layer.group_add(self.round_group_name, self.channel_name)

        await self.accept()
        print(f"Round Consumer connection to {self.round_group_name} accepted.")

    async def disconnect(self, close_code):
        # Leave room group
        await self.channel_layer.group_discard(self.round_group_name, self.channel_name)

    # Receive message from WebSocket
    async def receive(self, text_data):
        # We can handle client-to-server messages here if needed
        pass

    # Receive message from room group
    async def round_update(self, event):
        # Send message to WebSocket
        await self.send(
            text_data=json.dumps(
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
                }
            )
        )

    # Receive message from room group
    async def session_update(self, event):
        # Send message to WebSocket
        await self.send(
            text_data=json.dumps(
                {
                    "is_paused": event["is paused"],
                    "time_spent": event["time spent"],
                    "session_update": True,
                    "driver_id": event["driver id"],
                    "driver_status": event["driver status"],
                    "completed_sessions": event["completed sessions"],
                }
            )
        )

    async def pause_update(self, event):
        # Send message to WebSocket
        await self.send(
            text_data=json.dumps(
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
        await self.send(
            text_data=json.dumps(
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
        await self.send(
            text_data=json.dumps(
                {
                    "type": "race_lap_update",
                    "race_id": event["race_id"],
                    "team_number": event["team_number"],
                    "lap_number": event["lap_number"],
                    "is_suspicious": event.get("is_suspicious", False),
                    "crossing_id": event.get("crossing_id"),
                }
            )
        )

    async def race_finished(self, event):
        """Broadcast race finished notification to race control"""
        await self.send(
            text_data=json.dumps(
                {
                    "type": "race_finished",
                    "race_id": event["race_id"],
                    "race_type": event["race_type"],
                }
            )
        )


class StopAndGoConsumer(AsyncWebsocketConsumer):
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
        print("Stop and Go station connected")

    async def disconnect(self, close_code):
        # Leave room group
        await self.channel_layer.group_discard(
            self.stopandgo_group_name, self.channel_name
        )
        print("Stop and Go station disconnected")

    async def receive(self, text_data):
        try:
            data = json.loads(text_data)

            # Verify HMAC signature for all incoming messages
            provided_signature = data.pop("hmac_signature", None)
            if not provided_signature:
                print("Received message without HMAC signature")
                return

            if not self.verify_hmac(data, provided_signature):
                print("HMAC verification failed - rejecting message")
                return

            # Handle both race control commands and station responses
            message_type = data.get("type")

            if message_type == "response":
                # Handle station responses
                response_type = data.get("response")

                if response_type == "penalty_served":
                    team_number = data.get("team")
                    if team_number:
                        print(f"Penalty served by team {team_number}")

                        # Send signed acknowledgment back to station
                        message = {
                            "type": "penalty_acknowledged",
                            "team": team_number,
                            "timestamp": dt.datetime.now().isoformat(),
                        }
                        signed_message = self.sign_message(message)
                        await self.send(text_data=json.dumps(signed_message))

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
                        print(f"Penalty force completed for team {team_number}")
                        await self.channel_layer.group_send(
                            self.stopandgo_group_name,
                            {"type": "penalty_completed", "team": team_number},
                        )
            elif message_type == "penalty_acknowledged":
                # Handle penalty acknowledgment from race control
                team_number = data.get("team")
                if team_number:
                    print(f"Race control acknowledged penalty for team {team_number}")
                    # Send penalty_acknowledged message to station (not as command)
                    message = {
                        "type": "penalty_acknowledged",
                        "team": team_number,
                        "timestamp": dt.datetime.now().isoformat(),
                    }
                    signed_message = self.sign_message(message)
                    await self.send(text_data=json.dumps(signed_message))
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
            print("Invalid JSON received from stop and go connection")

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
        await self.send(text_data=json.dumps(signed_message))

    async def set_fence(self, event):
        # Send signed fence enable/disable command to station
        message = {
            "type": "command",
            "command": "set_fence",
            "enabled": event["enabled"],
            "timestamp": dt.datetime.now().isoformat(),
        }
        signed_message = self.sign_message(message)
        await self.send(text_data=json.dumps(signed_message))

    async def get_fence_status(self, event):
        # Send signed query for fence status from station
        message = {
            "type": "command",
            "command": "get_fence_status",
            "timestamp": dt.datetime.now().isoformat(),
        }
        signed_message = self.sign_message(message)
        await self.send(text_data=json.dumps(signed_message))

    async def force_complete_penalty(self, event):
        # Send signed force complete penalty command to station
        message = {
            "type": "command",
            "command": "force_complete",
            "timestamp": dt.datetime.now().isoformat(),
        }
        signed_message = self.sign_message(message)
        await self.send(text_data=json.dumps(signed_message))

    async def penalty_served(self, event):
        # Broadcast penalty served notification to race control interfaces
        await self.send(
            text_data=json.dumps({"type": "penalty_served", "team": event["team"]})
        )

    async def fence_status(self, event):
        # Broadcast fence status to race control interfaces
        await self.send(
            text_data=json.dumps({"type": "fence_status", "enabled": event["enabled"]})
        )

    async def penalty_completed(self, event):
        # Broadcast penalty completion notification to race control interfaces
        await self.send(
            text_data=json.dumps({"type": "penalty_completed", "team": event["team"]})
        )

    async def penalty_queue_update(self, event):
        # Broadcast penalty queue status update to race control interfaces
        await self.send(
            text_data=json.dumps(
                {
                    "type": "penalty_queue_update",
                    "serving_team": event["serving_team"],
                    "queue_count": event["queue_count"],
                    "round_id": event["round_id"],
                }
            )
        )

    async def race_lap_update(self, event):
        """Broadcast lap crossing updates to race control"""
        await self.send(
            text_data=json.dumps(
                {
                    "type": "race_lap_update",
                    "race_id": event["race_id"],
                    "team_number": event["team_number"],
                    "lap_number": event["lap_number"],
                    "is_suspicious": event.get("is_suspicious", False),
                    "crossing_id": event.get("crossing_id"),
                }
            )
        )

    async def race_finished(self, event):
        """Broadcast race finished notification to race control"""
        await self.send(
            text_data=json.dumps(
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
                print(
                    f"Processing station-reported penalty served for team {team_number}"
                )

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

                # Trigger next penalty after 10 seconds
                await self.trigger_next_penalty_after_delay(current_round.id)
            else:
                print(
                    f"Ignoring station penalty_served for team {team_number} - penalty already processed or not found"
                )

        except Exception as e:
            print(f"Error handling penalty served from station: {e}")

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
            print(f"Triggered next penalty for team {penalty_data['team_number']}")

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
        await self.send(text_data=json.dumps(signed_message))


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
    print(f"🏁 Race end requested for Round {round_id}")

    try:
        # Get the round instance
        round_instance = await Round.objects.aget(id=round_id)

        # Use the round's instance-level lock for thread safety
        async with round_instance._end_race_lock:
            if not round_instance.ended:
                print(f"🔒 Ending race {round_id} with lock protection")
                await sync_to_async(round_instance.end_race)()
                print(f"✅ Race {round_id} ended successfully")
            else:
                print(f"⚠️ Race {round_id} already ended - skipping")

    except Exception as e:
        print(f"❌ Error ending race {round_id}: {e}")


class TimingConsumer(AsyncWebsocketConsumer):
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
        print("Timing daemon connected")

    async def disconnect(self, close_code):
        self._station_connected = False
        await self.channel_layer.group_discard(
            self.timing_group_name, self.channel_name
        )
        print("Timing daemon disconnected")

    async def receive(self, text_data):
        try:
            data = json.loads(text_data)

            provided_signature = data.pop("hmac_signature", None)
            if not provided_signature:
                print("Timing: Received message without HMAC signature")
                return

            if not self.verify_hmac(data, provided_signature):
                print("Timing: HMAC verification failed - rejecting message")
                return

            message_type = data.get("type")

            if message_type == "connected":
                timing_mode = data.get("timing_mode", "duration")
                if timing_mode not in self.VALID_TIMING_MODES:
                    print(f"Timing: Invalid timing_mode '{timing_mode}', rejecting")
                    return
                self._timing_mode = timing_mode
                self._rollover_seconds = float(data.get("rollover_seconds", 360000.0))
                self._station_connected = True
                print(
                    f"Timing station connected: plugin={data.get('plugin_type')} "
                    f"mode={self._timing_mode} rollover={self._rollover_seconds}"
                )

            elif message_type == "lap_crossing":
                if not self._station_connected:
                    print("Timing: lap_crossing before connected message, ignoring")
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
                print(f"Timing warning: {data.get('message')}")

            elif message_type == "response":
                print(f"Timing response: {data.get('response')}")

        except json.JSONDecodeError:
            print("Timing: Invalid JSON received")
        except Exception as e:
            print(f"Timing: Error processing message: {e}")

    async def send_ack(self, message_id):
        """Send ACK for a processed crossing back to the station."""
        message = {"type": "ack", "message_id": message_id}
        signed = self.sign_message(message)
        await self.send(text_data=json.dumps(signed))

    async def _broadcast_crossing(self, result):
        """Broadcast crossing data to leaderboard and race control groups."""
        race_id = result["race_id"]
        round_id = result["round_id"]
        team_number = result["team_number"]
        lap_number = result["lap_number"]
        lap_time = result["lap_time"]
        is_suspicious = result["is_suspicious"]

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
                "is_suspicious": is_suspicious,
                "crossing_id": result.get("crossing_id"),
            },
        )

        if result.get("grid_violation"):
            await self.channel_layer.group_send(
                f"round_{round_id}",
                {"type": "grid_violation", **result["grid_violation"]},
            )

        if result.get("race_finished"):
            print(f"Race {race_id} finished!")
            await self.channel_layer.group_send(
                f"round_{round_id}",
                {
                    "type": "race_finished",
                    "race_id": race_id,
                    "race_type": result["race_type"],
                },
            )

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
                    print(f"Timing: Duplicate message_id {message_id[:8]}, skipping")
                    return None
            else:
                msg_uuid = None

            # Get transponder
            transponder = Transponder.objects.filter(
                transponder_id=transponder_id
            ).first()

            if not transponder:
                print(f"Timing: Unknown transponder {transponder_id}")
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
                )
                .select_related("race", "race__round", "team", "team__team")
                .first()
            )

            if not assignment:
                print(
                    f"Timing: No active race assignment for transponder {transponder_id}"
                )
                return None

            race = assignment.race
            team = assignment.team

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
                print(
                    f"Timing: Transponder dedup — team {team.number} "
                    f"already crossed within {TRANSPONDER_DEDUP_SECONDS}s, skipping"
                )
                return None

            # Get last crossing for this team (for lap number and raw_time reference)
            last_crossing = (
                LapCrossing.objects.filter(race=race, team=team, is_valid=True)
                .order_by("-lap_number")
                .first()
            )

            lap_number = (last_crossing.lap_number + 1) if last_crossing else 1

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
            if lap_time and should_count:
                if self.is_lap_suspicious(race, lap_time, team):
                    crossing.is_suspicious = True
                    crossing.save(update_fields=["is_suspicious"])
                    print(
                        f"Suspicious lap: Team {team_number}, "
                        f"Lap {lap_number}, Time {lap_time}"
                    )

            print(
                f"Lap recorded: Team {team_number}, Lap {lap_number}, "
                f"Time: {lap_time}, raw={raw_time}"
            )

            # Trigger Race.started on first crossing (FIRST_CROSSING mode)
            race_started = False
            if (
                lap_number == 1
                and race.started is None
                and race.start_mode != "IMMEDIATE"
            ):
                race.started = crossing_time
                race.save(update_fields=["started"])
                race_started = True

            race_finished = race.is_race_finished()

            result = {
                "race_id": race.id,
                "round_id": race.round.id,
                "team_number": team_number,
                "lap_number": lap_number,
                "lap_time": lap_time,
                "is_suspicious": crossing.is_suspicious,
                "crossing_id": crossing.id,
                "race_finished": race_finished,
                "race_type": race.race_type if race_finished else None,
                "race_started": race_started,
            }

            # Grid order check (MAIN race only, driven by ChampionshipPenalty)
            if lap_number == 1 and race.race_type == "MAIN":
                grid_order_penalty = ChampionshipPenalty.objects.filter(
                    championship=race.round.championship,
                    penalty__name="grid order",
                ).first()
                if grid_order_penalty:
                    grid_pos = GridPosition.objects.filter(race=race, team=team).first()
                    crossing_order = LapCrossing.objects.filter(
                        race=race, lap_number=1
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
            print(f"Timing: Error handling lap crossing: {e}")
            return None

    def is_lap_suspicious(self, race, lap_time, team=None):
        """
        Check if lap time is suspicious (>2x median).
        """
        try:
            filters = {"race": race, "is_valid": True, "lap_time__isnull": False}
            if team:
                filters["team"] = team

            valid_laps = LapCrossing.objects.filter(**filters)

            if valid_laps.count() < 3:
                return False

            lap_times = [lap.lap_time.total_seconds() for lap in valid_laps]
            lap_times.sort()
            median_time = lap_times[len(lap_times) // 2]

            return lap_time.total_seconds() > (median_time * 2)

        except Exception:
            return False

    async def send_command(self, command_type, **kwargs):
        """Send command to timing daemon"""
        message = {"type": "command", "command": command_type, **kwargs}
        signed = self.sign_message(message)
        await self.send(text_data=json.dumps(signed))


class LeaderboardConsumer(AsyncWebsocketConsumer):
    """
    WebSocket consumer for real-time leaderboard updates.
    Broadcasts standings updates when lap crossings occur.
    """

    async def connect(self):
        self.race_id = self.scope["url_route"]["kwargs"]["race_id"]
        self.race_group_name = f"leaderboard_{self.race_id}"

        # Join race leaderboard group
        await self.channel_layer.group_add(self.race_group_name, self.channel_name)

        await self.accept()

        # Send initial standings
        standings = await self.get_current_standings()
        await self.send(
            text_data=json.dumps({"type": "standings_update", "standings": standings})
        )

    async def disconnect(self, close_code):
        # Leave race leaderboard group
        await self.channel_layer.group_discard(self.race_group_name, self.channel_name)

    async def receive(self, text_data):
        """Handle incoming messages — supports reload requests"""
        try:
            data = json.loads(text_data)
            if data.get("type") == "reload":
                standings = await self.get_current_standings()
                await self.send(
                    text_data=json.dumps(
                        {"type": "standings_update", "standings": standings}
                    )
                )
        except json.JSONDecodeError:
            pass

    async def lap_crossing_update(self, event):
        """
        Called when a lap crossing occurs.
        Recalculate and broadcast standings.
        """
        # Debounce: only send updates at most once per second
        current_time = time.time()
        if not hasattr(self, "_last_update"):
            self._last_update = 0

        if current_time - self._last_update < 1.0:
            return  # Skip this update

        self._last_update = current_time

        standings = await self.get_current_standings()
        await self.send(
            text_data=json.dumps(
                {
                    "type": "standings_update",
                    "standings": standings,
                    "flash_team_number": event.get("crossing_data", {}).get(
                        "team_number"
                    ),
                }
            )
        )

    @database_sync_to_async
    def get_current_standings(self):
        """Get current race standings"""
        try:
            race = Race.objects.get(id=self.race_id)
            return race.calculate_race_standings()
        except Race.DoesNotExist:
            return []


class TransponderScanConsumer(AsyncWebsocketConsumer):
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
        await self.send(
            text_data=json.dumps(
                {
                    "type": "transponder_detected",
                    "transponder_id": event["transponder_id"],
                    "timestamp": event["timestamp"],
                }
            )
        )
