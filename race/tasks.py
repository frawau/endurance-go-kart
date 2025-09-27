# race/tasks.py

import asyncio as aio
import datetime as dt
from django.db.models import Q
from asgiref.sync import sync_to_async
from .signals import race_end_requested


class RaceTasks:

    _lock = aio.Semaphore(1)

    @classmethod
    async def race_events(cls):
        # Try to acquire the semaphore
        if not cls._lock.locked():
            async with cls._lock:
                from .models import Round, ChangeLane

                end_date = dt.date.today()
                start_date = end_date - dt.timedelta(days=1)
                cround = await Round.objects.filter(
                    Q(start__date__range=[start_date, end_date]) & Q(ended__isnull=True)
                ).afirst()
                if not cround:
                    return
                if not cround.ready:
                    # nothing to do
                    return

                if not cround.started:
                    # Nothing to do
                    return

                if cround.ended:
                    # Nothing to do
                    return

                elapsed = await cround.async_time_elapsed()
                if elapsed < cround.pitlane_open_after:
                    # Do we wait for it?
                    if (cround.pitlane_open_after) - elapsed <= dt.timedelta(
                        seconds=65
                    ):
                        dowait = (cround.pitlane_open_after - elapsed).total_seconds()
                        while int(dowait) > 0:
                            await aio.sleep(dowait)
                            elapsed = await cround.async_time_elapsed()
                            dowait = (
                                cround.pitlane_open_after - elapsed
                            ).total_seconds()
                        change_lanes = await sync_to_async(list)(
                            ChangeLane.objects.filter(round=cround, open=False)
                        )
                        for alane in change_lanes:
                            alane.open = True
                            await alane.asave()
                elif cround.duration - elapsed < dt.timedelta(seconds=65):
                    # Check for end before check for close pit lane. Would not be reached otherwise
                    dowait = (cround.duration - elapsed).total_seconds()
                    print(f"\n\n\nClosing in {dowait} seconds!\n\n\n")
                    while int(dowait) > 0:
                        await aio.sleep(dowait)
                        elapsed = await cround.async_time_elapsed()
                        dowait = (cround.duration - elapsed).total_seconds()
                        if not cround.ended:
                            await race_end_requested.asend(
                                sender=cls, round_id=cround.id
                            )
                elif (
                    cround.duration - elapsed - cround.pitlane_close_before
                    < dt.timedelta(seconds=65)
                ):
                    dowait = (
                        cround.duration - elapsed - cround.pitlane_close_before
                    ).total_seconds()
                    while int(dowait) > 0:
                        await aio.sleep(dowait)
                        elapsed = await cround.async_time_elapsed()
                        dowait = (
                            cround.duration - elapsed - cround.pitlane_close_before
                        ).total_seconds()
                    change_lanes = await sync_to_async(list)(
                        ChangeLane.objects.filter(
                            round=cround, open=True, driver__isnull=True
                        )
                    )
                    for alane in change_lanes:
                        alane.open = False
                        await alane.asave()

        else:
            # bail out
            return


def run_race_events():
    """Wrapper function to run the async race_events task."""
    aio.run(RaceTasks.race_events())
