# serializers.py
from rest_framework import serializers
from .models import ChangeLane, team_member


class ChangeLaneSerializer(serializers.ModelSerializer):
    driver = serializers.PrimaryKeyRelatedField(
        queryset=team_member.objects.all(), allow_null=True
    )

    class Meta:
        model = ChangeLane
        depth = 2
        fields = ["id", "lane", "open", "driver"]  # add other fields as needed.
