from django.db.models.signals import post_save, post_delete, pre_delete
from django.dispatch import receiver, Signal
from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync
from .models import (
    ChangeLane,
    round_pause,
    team_member,
    round_team,
    Round,
    Race,
    Session,
    PenaltyQueue,
)
from django.template.loader import render_to_string
from django.db.models import Count

# Custom signal for race end requests
# Arguments: round_id (int)
race_end_requested = Signal()

# Function to update all connected clients
def update_empty_teams(round_id):
    # Get the channel layer
    channel_layer = get_channel_layer()

    # Get the current empty teams
    teams_without_members = list(
        round_team.objects.filter(round_id=round_id)
        .annotate(member_count=Count("team_member"))
        .filter(member_count=0)
        .select_related("team__championship", "team__team")
    )

    # Format the teams data
    empty_teams = [
        {
            "id": rt.id,
            "team_name": rt.team.team.name,
            "number": rt.team.number,
            "championship_name": rt.team.championship.name,
        }
        for rt in teams_without_members
    ]

    # Send update to the room group
    async_to_sync(channel_layer.group_send)(
        f"empty_teams_{round_id}", {"type": "empty_teams_list", "teams": empty_teams}
    )


# Listen for team member changes
@receiver([post_save, post_delete], sender=team_member)
def team_member_changed(sender, instance, **kwargs):
    """Called when a team member is added, changed or deleted"""
    # Get the round ID from the team
    round_id = instance.team.round_id

    # Update empty teams for this round
    update_empty_teams(round_id)


# Listen for round team changes
@receiver([post_save, post_delete], sender=round_team)
def round_team_changed(sender, instance, **kwargs):
    """Called when a round team is added, changed or deleted"""
    # Update empty teams for this round
    update_empty_teams(instance.round_id)


@receiver(post_save, sender=ChangeLane)
def change_lane_updated(sender, instance, created, **kwargs):
    if not created:  # Only send updates if the instance was modified
        channel_layer = get_channel_layer()
        lane_html = render_to_string(
            "layout/changelane_detail.html", {"change_lane": instance}
        )
        async_to_sync(channel_layer.group_send)(
            f"lane_{instance.lane}",
            {
                "type": "lane.update",
                "lane_html": lane_html,
            },
        )

        lane_html = render_to_string(
            "layout/changelane_small_detail.html", {"change_lane": instance}
        )
        async_to_sync(channel_layer.group_send)(
            f"lane_{instance.lane}",
            {
                "type": "rclane.update",
                "lane_html": lane_html,
            },
        )

        change_lanes = ChangeLane.objects.filter(open=True).order_by("lane")
        driverc_html = render_to_string(
            "layout/changedriver_detail.html", {"change_lanes": change_lanes}
        )

        async_to_sync(channel_layer.group_send)(
            "changedriver",
            {
                "type": "changedriver.update",
                "driverc_html": driverc_html,
            },
        )


@receiver(post_delete, sender=ChangeLane)
def change_lane_deleted(sender, instance, **kwargs):
    # Add logic here if you want to send a websocket message when a lane is deleted.
    pass


def _build_round_update_payload(cround):
    """Build the common payload dict for round/race/pause updates."""
    active = cround.active_race  # None for legacy rounds

    if active:
        remaining = round(
            (active.duration - active.time_elapsed).total_seconds()
            if active.started
            else active.duration.total_seconds()
        )
        started = active.started is not None
        ready = active.ready
        ended = False  # active_race is always unfinished
        armed = active.ready and active.started is None and cround.started is not None
        start_mode = active.start_mode
    else:
        # Legacy round or all races finished
        if not cround.uses_legacy_session_model and cround.ended:
            # All races done
            remaining = 0
            started = True
            ready = True
            ended = True
        else:
            # Legacy path
            remaining = round(
                (cround.duration - cround.time_elapsed).total_seconds()
                if cround.started
                else cround.duration.total_seconds()
            )
            started = cround.started is not None
            ready = cround.ready
            ended = cround.ended is not None

    return {
        "is paused": cround.is_paused,
        "remaining seconds": remaining,
        "started": started,
        "ready": ready,
        "ended": ended,
        "armed": armed if active else False,
        "start_mode": start_mode if active else None,
        "active_race_type": active.race_type if active else None,
        "active_race_label": active.get_race_type_display() if active else None,
        "has_more_races": active is not None,
    }


@receiver(post_save, sender=round_pause)
def handle_pause_change(sender, instance, **kwargs):
    cround = instance.round
    payload = _build_round_update_payload(cround)
    payload["type"] = "pause_update"

    channel_layer = get_channel_layer()
    async_to_sync(channel_layer.group_send)(f"round_{cround.id}", payload)


@receiver(post_save, sender=Round)
def handle_round_change(sender, instance, **kwargs):
    """Handle round state changes (started, ended) for timer updates"""
    payload = _build_round_update_payload(instance)
    payload["type"] = "round_update"

    channel_layer = get_channel_layer()
    async_to_sync(channel_layer.group_send)(f"round_{instance.id}", payload)


@receiver(post_save, sender=Race)
def handle_race_change(sender, instance, **kwargs):
    """Handle race state changes for multi-race rounds."""
    cround = instance.round
    payload = _build_round_update_payload(cround)
    payload["type"] = "round_update"

    channel_layer = get_channel_layer()
    async_to_sync(channel_layer.group_send)(f"round_{cround.id}", payload)


@receiver(post_save, sender=Session)
def handle_session_change(sender, instance, **kwargs):
    """Handle session changes for driver timer updates"""
    round_instance = instance.round
    driver = instance.driver
    if instance.end:
        dstatus = "end"
    elif instance.start:
        dstatus = "start"
    elif instance.register:
        dstatus = "register"
    else:
        dstatus = "reset"
    # Get the round_team for this driver
    round_team = driver.team

    # Count completed sessions for this team
    if round_instance.started:
        completed_sessions_count = Session.objects.filter(
            driver__team=round_team, end__isnull=False
        ).count()
    else:
        completed_sessions_count = -1

    channel_layer = get_channel_layer()
    # First update the round timer
    async_to_sync(channel_layer.group_send)(
        f"round_{round_instance.id}",
        {
            "type": "session_update",
            "is paused": round_instance.is_paused,
            "time spent": round(driver.time_spent.total_seconds()),
            "driver id": driver.id,
            "driver status": dstatus,
            "completed sessions": completed_sessions_count,
        },
    )


def send_penalty_queue_update(round_id):
    """Send penalty queue status update to WebSocket clients"""
    channel_layer = get_channel_layer()

    # Get the next penalty in queue (oldest timestamp)
    next_penalty = PenaltyQueue.get_next_penalty(round_id)

    # Count total penalties in queue for this round
    queue_count = PenaltyQueue.objects.filter(round_penalty__round_id=round_id).count()

    # Get serving team number if there's an active penalty
    serving_team = None
    if next_penalty and next_penalty.round_penalty.offender:
        serving_team = next_penalty.round_penalty.offender.team.number

    # Send update to stopandgo channel
    async_to_sync(channel_layer.group_send)(
        "stopandgo",
        {
            "type": "penalty_queue_update",
            "serving_team": serving_team,
            "queue_count": queue_count,
            "round_id": round_id,
        },
    )


@receiver([post_save, post_delete], sender=PenaltyQueue)
def penalty_queue_changed(sender, instance, **kwargs):
    """Called when a PenaltyQueue entry is created, updated, or deleted"""
    round_id = instance.round_penalty.round.id
    send_penalty_queue_update(round_id)


@receiver(pre_delete, sender=Session)
def handle_session_delete(sender, instance, **kwargs):
    round_instance = instance.round
    driver = instance.driver
    dstatus = "reset"
    # Count completed sessions for this team
    if round_instance.started:
        try:
            completed_sessions_count = Session.objects.filter(
                driver__team=driver.team, end__isnull=False
            ).count()
        except:
            return
    else:
        completed_sessions_count = -1
    channel_layer = get_channel_layer()
    # First update the round timer
    async_to_sync(channel_layer.group_send)(
        f"round_{round_instance.id}",
        {
            "type": "session_update",
            "is paused": round_instance.is_paused,
            "time spent": round(driver.time_spent.total_seconds()),
            "driver id": driver.id,
            "driver status": dstatus,
            "completed sessions": completed_sessions_count,
        },
    )
