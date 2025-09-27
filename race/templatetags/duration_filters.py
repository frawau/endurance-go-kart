from django import template

register = template.Library()


@register.filter
def duration_difference_seconds(round):
    if round:
        return (round.duration - round.time_elapsed).total_seconds()
    return 0


@register.filter
def round_is_paused(round):
    if round:
        return "true" if round.is_paused else "false"
    return "true"


@register.filter
def mmss_format(timedelta_obj):
    """Format timedelta as MM:SS for form inputs"""
    if not timedelta_obj:
        return "00:00"

    total_seconds = int(timedelta_obj.total_seconds())
    minutes = total_seconds // 60
    seconds = total_seconds % 60
    return f"{minutes:02d}:{seconds:02d}"


@register.filter
def duration_format(seconds):
    """Format seconds as HH:MM:SS or MM:SS"""
    if seconds is None:
        return ""

    try:
        total_seconds = int(float(seconds))
        hours = total_seconds // 3600
        minutes = (total_seconds % 3600) // 60
        secs = total_seconds % 60

        if hours > 0:
            return f"{hours:02d}:{minutes:02d}:{secs:02d}"
        else:
            return f"{minutes:02d}:{secs:02d}"
    except (ValueError, TypeError):
        return ""
