from django.urls import path
from channels.security.websocket import AllowedHostsOriginValidator

from . import consumers


def _browser(consumer):
    """Wrap a browser-facing consumer with cross-origin (CSWSH) protection.

    AllowedHostsOriginValidator rejects WebSocket connections whose Origin
    header is not in settings.ALLOWED_HOSTS, blocking cross-site WebSocket
    hijacking from a page an authenticated operator happens to visit.

    Station consumers (stop-and-go, timing) are intentionally NOT wrapped:
    they are opened by native Python daemons that send no Origin header
    (which this validator would reject) and are authenticated by HMAC.
    """
    return AllowedHostsOriginValidator(consumer.as_asgi())


websocket_urlpatterns = [
    path("ws/pitlanes/<int:pitlane_number>/", _browser(consumers.ChangeLaneConsumer)),
    path("ws/changedriver/", _browser(consumers.ChangeDriverConsumer)),
    path("ws/empty_teams/", _browser(consumers.EmptyTeamsConsumer)),
    path("ws/round/<int:round_id>/", _browser(consumers.RoundConsumer)),
    path("ws/stopandgo/", consumers.StopAndGoConsumer.as_asgi()),
    path("ws/stopandgo-display/", _browser(consumers.StopAndGoCallScreenConsumer)),
    path("ws/timing/", consumers.TimingConsumer.as_asgi()),
    path("ws/leaderboard/<int:race_id>/", _browser(consumers.LeaderboardConsumer)),
    path("ws/transponder-scan/", _browser(consumers.TransponderScanConsumer)),
]
