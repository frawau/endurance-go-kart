# yourapp/templatetags/round_tags.py
from django import template

register = template.Library()


@register.simple_tag
def check_driver_transgression(member):
    """
    Check if a team member has a transgression.
    Returns True or False.
    """
    return member.has_transgression


@register.simple_tag
def check_team_transgression(round_team):
    """
    Check if a team has a transgression.

    """
    return round_team.has_transgression


@register.filter
def format_time(timedelta):
    """Format a timedelta as HH:MM:SS without microseconds"""
    if not timedelta:
        return "00:00:00"

    # Calculate total seconds
    total_seconds = int(timedelta.total_seconds())
    # Calculate hours, minutes, seconds
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    seconds = total_seconds % 60

    # Format as HH:MM:SS
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
