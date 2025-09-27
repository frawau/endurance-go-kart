from django.urls import path
from . import consumers

websocket_urlpatterns = [
    path("ws/pitlanes/<int:pitlane_number>/", consumers.ChangeLaneConsumer.as_asgi()),
    path("ws/changedriver/", consumers.ChangeDriverConsumer.as_asgi()),
    path("ws/empty_teams/", consumers.EmptyTeamsConsumer.as_asgi()),
    path("ws/round/<int:round_id>/", consumers.RoundConsumer.as_asgi()),
    path("ws/stopandgo/", consumers.StopAndGoConsumer.as_asgi()),
]
