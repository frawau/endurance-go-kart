# race/context_processors.py
import datetime as dt
from django.db.models import Q
from django.core.cache import cache
from race.models import Round, Race, Config


def active_round_data(request):
    # Try to get from cache first
    locv = cache.get("active_cache_keys")
    myvals = {}

    if locv is None:
        locv = "active_round_change_lanes,has_active_round"
        # Value not in cache, fetch from database
        end_date = dt.date.today()
        start_date = end_date - dt.timedelta(days=1)
        cround = Round.objects.filter(
            Q(start__date__range=[start_date, end_date]) & Q(ended__isnull=True)
        ).first()

        myvals["active_round_change_lanes"] = cround.change_lanes if cround else 0
        myvals["has_active_round"] = cround is not None

        # Cache the value for 3 hours
        cache.set(
            "active_round_change_lanes",
            myvals["active_round_change_lanes"],
            3 * 60 * 60,
        )
        cache.set("has_active_round", myvals["has_active_round"], 3 * 60 * 60)

        props = Config.objects.all()
        for aprop in props:
            locv += "," + aprop.name.replace(" ", "_")
            myvals[aprop.name.replace(" ", "_")] = aprop.value
            cache.set(aprop.name.replace(" ", "_"), aprop.value, 3 * 60 * 60)

        cache.set("active_cache_keys", locv, 3 * 60 * 60)
    else:
        for k in locv.split(","):
            myvals[k] = cache.get(k)

    # Always look up active_race_id fresh (cheap query, changes when Race is created/started)
    active_race = None
    active_cround = None
    if myvals.get("has_active_round"):
        end_date = dt.date.today()
        start_date = end_date - dt.timedelta(days=1)
        active_cround = Round.objects.filter(
            Q(start__date__range=[start_date, end_date]) & Q(ended__isnull=True)
        ).first()
        if active_cround:
            active_race = (
                Race.objects.filter(round=active_cround, ended__isnull=True)
                .order_by("sequence_number")
                .first()
            )
    myvals["active_race_id"] = active_race.id if active_race else None
    myvals["active_round_has_timing"] = (
        active_cround is not None and not active_cround.uses_legacy_session_model
    )

    # Penalty-menu visibility flags. Cheap queries, only when there is an
    # active timing round. They drive Setup Round menu entries that
    # pre-select the active round's Main race:
    #   - Grid Penalty: a Main race exists, hasn't started, grid not locked.
    #   - Lap & Time Penalties (post-race): a Main race has ended and the
    #     round results are not yet confirmed.
    # active_main_race_id is the active round's Main race id (any state),
    # used as the ?race_id pre-selection target on those pages.
    grid_penalty_available = False
    post_race_penalty_available = False
    active_main_race_id = None
    if active_cround is not None and not active_cround.uses_legacy_session_model:
        main_race = (
            Race.objects.filter(round=active_cround, race_type="MAIN")
            .order_by("sequence_number")
            .first()
        )
        if main_race is not None:
            active_main_race_id = main_race.id
            grid_penalty_available = (
                main_race.started is None and not main_race.grid_locked
            )
            if not active_cround.results_confirmed:
                post_race_penalty_available = main_race.ended is not None
    myvals["grid_penalty_available"] = grid_penalty_available
    myvals["post_race_penalty_available"] = post_race_penalty_available
    myvals["active_main_race_id"] = active_main_race_id

    return myvals
