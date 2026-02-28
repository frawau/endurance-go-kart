# raceinfo/templatetags/timer_tags.py
# (Replace 'raceinfo' with your actual Django app name if different)

from django import template
from django.utils.safestring import mark_safe
from race.models import Session  # Import your Session model
import json
import datetime as dt  # Import datetime for type checking and timedelta operations


register = template.Library()


@register.simple_tag
def timer_widget(
    element_id,
    timer_type,
    instance=None,
    initial_value=None,
    show_hours=True,
    show_minutes=True,
    limit=None,
):
    """
    Renders a timer widget span element for initialization by timer-widget.js.

    Args:
        element_id (str): The base HTML element ID (e.g., "total-time-").
                          The instance ID will be appended for member timers,
                          or used directly for round timers.
        timer_type (str): One of 'countdownDisplay', 'totaltime', or 'sessiontime'.
        instance (Model Instance): The model instance (Round or team_member). Required for configuration.
        initial_value (float, optional): Override calculated startValue. Defaults to None.
        show_hours (bool): Whether to include hours in the display format. Defaults to True.
        show_minutes (bool): Whether to include minutes in the display format. Defaults to True.
        limit (float, optional): Optional limit value (in seconds) for the timer to mark as "over". Defaults to None.
    """
    # If no instance provided, we cannot configure the timer properly.
    # Return a placeholder or an error comment.
    if not instance:
        # Ensure element_id is safe if used directly
        safe_element_id = str(element_id).replace(" ", "_").replace(":", "-")
        return mark_safe(
            f'<span id="{safe_element_id}" class="timer text-muted">--:--:--</span> '
        )

    # Determine the final element ID based on instance type and timer type
    final_element_id = str(element_id)  # Default for round timer
    instance_id_str = ""  # Store instance ID if applicable

    if hasattr(instance, "id"):
        instance_id_str = str(instance.id)  # Get instance ID safely

    if timer_type in ["totaltime", "sessiontime"] and instance_id_str:
        # Append instance ID for driver-specific timers
        final_element_id = f"{element_id}{instance_id_str}"
    elif timer_type == "countdownDisplay":
        # For countdown, use the passed element_id directly (e.g., "race-countdown")
        final_element_id = str(element_id)
    # else: handle potential other cases or keep default element_id

    # Default configuration dictionary
    config = {
        "elementId": final_element_id,  # Use the final determined ID
        "showHours": bool(show_hours),  # Ensure boolean
        "showMinutes": bool(show_minutes),  # Ensure boolean
        "timerType": timer_type,
        "startValue": 0,  # Default start value
        "countDirection": "up",  # Default direction
        "initialPaused": True,  # Default to paused
        "targetId": None,
    }

    # Add limit to config if provided
    # print(f"Generating time for {final_element_id} with limit {limit}")
    if limit is not None:
        try:
            config["limit"] = float(limit)
        except (ValueError, TypeError):
            print(
                f"Warning: Invalid limit value '{limit}' for timer {final_element_id}. Ignoring limit."
            )

    try:
        # --- Configure based on timer_type and instance type ---

        if timer_type == "countdownDisplay" and hasattr(
            instance, "duration"
        ):  # Instance is a Round
            round_instance = instance
            initial_seconds = (
                round_instance.duration.total_seconds()
                if round_instance.duration
                else 0
            )

            # Calculate remaining time accurately
            if round_instance.started and not round_instance.ended:
                # Ensure time_elapsed calculation handles potential None values if needed
                elapsed_seconds = (
                    round_instance.time_elapsed.total_seconds()
                    if isinstance(round_instance.time_elapsed, dt.timedelta)
                    else 0
                )
                remaining = initial_seconds - elapsed_seconds
            elif not round_instance.started:
                remaining = initial_seconds  # Not started, show full duration
            else:  # Ended
                remaining = 0  # Race finished

            config.update(
                {
                    "startValue": max(0, remaining),  # Don't start negative
                    "countDirection": "down",
                    # Pause if not started OR explicitly paused OR ended
                    "initialPaused": not round_instance.started
                    or round_instance.is_paused
                    or round_instance.ended,
                }
            )

        elif timer_type == "totaltime" and hasattr(
            instance, "time_spent"
        ):  # Instance is a team_member
            member = instance
            # Ensure time_spent calculation returns timedelta
            time_spent_delta = (
                member.time_spent
                if isinstance(member.time_spent, dt.timedelta)
                else dt.timedelta()
            )
            initial_seconds = time_spent_delta.total_seconds()
            round_instance = member.team.round  # Get the related round

            config.update(
                {
                    "startValue": initial_seconds,
                    "countDirection": "up",
                    # Pause if driver not on track OR round not started OR round paused OR round ended
                    "initialPaused": not member.ontrack
                    or not round_instance.started
                    or round_instance.is_paused
                    or round_instance.ended,
                    "targetId": member.id,
                }
            )

        elif timer_type == "sessiontime" and hasattr(
            instance, "ontrack"
        ):  # Instance is a team_member
            member = instance
            round_instance = member.team.round  # Get the related round

            # Session timer always starts from 0 when activated by JS.
            # Set startValue to 0 here for consistency.
            initial_seconds = member.current_session.total_seconds()

            config.update(
                {
                    "startValue": initial_seconds,
                    "countDirection": "up",
                    # Pause if driver not on track OR round not started OR round paused OR round ended
                    "initialPaused": not member.ontrack
                    or not round_instance.started
                    or round_instance.is_paused
                    or round_instance.ended,
                    "roundId": round_instance.id,
                    "targetId": member.id,
                }
            )

        else:
            # Handle cases where instance type doesn't match timer_type expectation
            print(
                f"Warning: Mismatched instance/type for timer widget {final_element_id}. Type: {timer_type}, Instance: {type(instance)}"
            )
            return mark_safe(
                f'<span id="{final_element_id}" class="timer text-danger">Config Error</span> '
            )

    except AttributeError as e:
        # Catch potential errors during attribute access (e.g., related object doesn't exist like member.team.round)
        print(
            f"Error configuring timer widget {final_element_id} (AttributeError): {e}"
        )  # Log error server-side
        return mark_safe(
            f'<span id="{final_element_id}" class="timer text-danger">Error</span> '
        )
    except Exception as e:
        # Catch other potential errors during configuration
        print(
            f"Error configuring timer widget {final_element_id} (General Exception): {e}"
        )  # Log error server-side
        return mark_safe(
            f'<span id="{final_element_id}" class="timer text-danger">Error</span> '
        )

    # Allow overriding the calculated startValue if explicitly provided via tag argument
    if initial_value is not None:
        try:
            config["startValue"] = float(initial_value)
        except (ValueError, TypeError):
            print(
                f"Warning: Invalid initial_value '{initial_value}' for timer {final_element_id}. Using calculated value."
            )

    # Serialize config safely for HTML data attribute
    # Use json.dumps with separators to minimize output size slightly
    json_config = json.dumps(config, separators=(",", ":"))

    # --- Determine Initial Display Text ---
    initial_display_text = (
        "--:--:--"  # Default placeholder for errors or unhandled cases
    )

    # Check if configuration was successful before setting initial text
    if "startValue" in config:  # Basic check that config likely succeeded
        if timer_type == "sessiontime" and config.get("initialPaused", True):
            # If it's a session timer AND it starts paused (inactive), display nothing initially
            initial_display_text = ""
        elif (
            config.get("startValue", 0) == 0
            and config.get("countDirection", "up") == "up"
        ):
            # For count-up timers starting at 0, display 00:00:00 initially
            # (Adjust formatting based on showHours/showMinutes)
            if config.get("showHours", True):
                initial_display_text = "00:00:00"
            elif config.get("showMinutes", True):
                initial_display_text = "00:00"
            else:
                initial_display_text = "00"
        else:
            # For countdown or countup not starting at 0, could format initial value
            # For simplicity, keep placeholder, JS will format on init render
            initial_display_text = "--:--:--"

    # Create the HTML span element for the timer widget
    # The initial text content will be replaced by timer-widget.js on initialization
    html = f'<span id="{final_element_id}" class="timer" data-timer="true" data-config=\'{json_config}\'>{initial_display_text}</span>'

    return mark_safe(html)


@register.simple_tag
def get_driver_time_limit(round_obj, team):
    """
    Get driver time limit information from a round object for a specific team.
    Returns a dict with mode and seconds.

    Usage:
    {% get_driver_time_limit round team as driver_limit %}
    {{ driver_limit.mode }} - {{ driver_limit.seconds }}
    """
    try:
        # Call the driver_time_limit method
        mode, time_delta = round_obj.driver_time_limit(team)

        # Convert timedelta to seconds if it's a timedelta
        seconds = (
            time_delta.total_seconds() if hasattr(time_delta, "total_seconds") else None
        )

        # Return as a dictionary for easy access in template
        return {"mode": mode, "seconds": seconds}
    except Exception as e:
        print(f"Error getting driver time limit: {e}")
        return {"mode": None, "seconds": None}


@register.simple_tag
def get_completed_sessions_count(round_team):
    """Return count of completed sessions (with end not NULL) for the active race."""
    active_race = round_team.round.active_race
    if active_race is None:
        return 0
    return Session.objects.filter(
        driver__team=round_team, race=active_race, end__isnull=False
    ).count()


@register.filter
def positive_only(value):
    try:
        return max(int(value), 0)
    except (ValueError, TypeError):
        return 0


@register.simple_tag
def driver_exceeded_limit(member, driver_limit):
    """
    Check if a driver has exceeded their time limit.

    Args:
        member: team_member instance
        driver_limit: dict with 'mode' and 'seconds' keys

    Returns:
        True if driver exceeded limit, False otherwise
    """
    if (
        not driver_limit
        or driver_limit.get("mode") is None
        or driver_limit.get("seconds") is None
    ):
        return False

    try:
        limit_seconds = float(driver_limit["seconds"])

        if driver_limit["mode"] == "race":
            # Check total driving time
            time_spent = (
                member.time_spent if hasattr(member, "time_spent") else dt.timedelta()
            )
            current_seconds = (
                time_spent.total_seconds()
                if isinstance(time_spent, dt.timedelta)
                else 0
            )
            return current_seconds > limit_seconds

        elif driver_limit["mode"] == "session":
            # Check current session time
            current_session = (
                member.current_session
                if hasattr(member, "current_session")
                else dt.timedelta()
            )
            current_seconds = (
                current_session.total_seconds()
                if isinstance(current_session, dt.timedelta)
                else 0
            )
            return current_seconds > limit_seconds

    except (AttributeError, ValueError, TypeError) as e:
        print(f"Error checking driver limit exceeded: {e}")
        return False

    return False
