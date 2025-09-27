# race/context_processors.py
import datetime as dt
from django.db.models import Q
from django.core.cache import cache
from race.models import Round, Config


def active_round_data(request):
    # Try to get from cache first
    locv = cache.get("active_cache_keys")
    myvals = {}

    if locv is None:
        locv = "active_round_change_lanes"
        # Value not in cache, fetch from database
        end_date = dt.date.today()
        start_date = end_date - dt.timedelta(days=1)
        cround = Round.objects.filter(
            Q(start__date__range=[start_date, end_date]) & Q(ended__isnull=True)
        ).first()

        myvals["active_round_change_lanes"] = cround.change_lanes if cround else 0

        # Cache the value for 1 hour (or however long you need)
        cache.set(
            "active_round_change_lanes",
            myvals["active_round_change_lanes"],
            3 * 60 * 60,
        )

        props = Config.objects.all()
        for aprop in props:
            locv += "," + aprop.name.replace(" ", "_")
            myvals[aprop.name.replace(" ", "_")] = aprop.value
            cache.set(aprop.name.replace(" ", "_"), aprop.value, 3 * 60 * 60)

        cache.set("active_cache_keys", locv, 3 * 60 * 60)
    else:
        for k in locv.split(","):
            myvals[k] = cache.get(k)

    return myvals
