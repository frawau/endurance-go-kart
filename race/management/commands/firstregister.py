import datetime as dt
from django.core.management.base import BaseCommand
from django.db.models import Q
from race.models import (
    Session,
    Round,
)


class Command(BaseCommand):
    help = "Register first driver for each team."

    def handle(self, *args, **options):

        start_date = dt.date.today() - dt.timedelta(days=1)
        end_date = start_date + dt.timedelta(days=60)
        cround = Round.objects.filter(
            Q(start__date__range=[start_date, end_date]) & Q(ended__isnull=True)
        ).first()
        if cround:
            # Register one driver per team
            teams = cround.round_team_set.all().order_by("team__number")
            now = dt.datetime.now()
            for team in teams:
                driver = team.team_member_set.filter(driver=True).order_by("?").first()
                asess = Session.objects.create(
                    round=cround, driver=driver, register=now
                )
                print(f"Added {driver}")
        else:
            print("Could not find a round")
