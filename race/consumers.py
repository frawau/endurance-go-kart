import asyncio
import json
import datetime as dt
import hmac
import hashlib
from django.conf import settings
from channels.generic.websocket import AsyncWebsocketConsumer
from .models import ChangeLane, round_team, team_member, championship_team, Round
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
