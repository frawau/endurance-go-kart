import uuid

from django.db import models
from django.db.models import Q, UniqueConstraint
from django_countries.fields import CountryField
from django.core.validators import MinValueValidator, MaxValueValidator
from django.core.exceptions import (
    ValidationError,
    ObjectDoesNotExist,
    MultipleObjectsReturned,
)
from django.contrib.auth.models import User
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from cryptography.fernet import Fernet
from asgiref.sync import sync_to_async

import asyncio
import datetime as dt
import logging

_log = logging.getLogger(__name__)
# Create your models here.


class UserProfile(models.Model):

    user = models.OneToOneField(User, on_delete=models.CASCADE)

    # __PROFILE_FIELDS__

    # __PROFILE_FIELDS__END

    def __str__(self):
        return self.user.username

    class Meta:
        verbose_name = _("User Profile")
        verbose_name_plural = _("User Profiles")


class Config(models.Model):
    name = models.CharField(max_length=128, unique=True)
    value = models.CharField(max_length=128)

    class Meta:
        verbose_name = _("Configuration")

    def __str__(self):
        return f"Config {self.name} is {self.value}"


def mugshot_path(instance, filename):
    # file will be uploaded to MEDIA_ROOT/user_<id>/<filename>
    return f"static/person/mug_{instance.surname}_{instance.country}_{round(dt.datetime.now().timestamp())}"


def illustration_path(instance, filename):
    return f"static/illustration/penalty_{instance.name}"


def logo_path(instance, filename):
    # file will be uploaded to MEDIA_ROOT/user_<id>/<filename>
    return f"static/logos/{instance.name}_{round(dt.datetime.now().timestamp())}"


def default_weight_penalty():
    return [
        ">=",
        [80, 0],
        [77.5, 2.5],
        [75, 5],
        [72.5, 7.5],
        [70, 10],
        [67.5, 12.5],
        [65, 15],
        [62.5, 17.5],
        [60, 20],
        [57.5, 22.5],
        [0, 25],
    ]


class Person(models.Model):
    GENDER = (
        ("M", "♂"),
        ("F", "♀"),
    )
    surname = models.CharField(max_length=32)
    firstname = models.CharField(max_length=32)
    nickname = models.CharField(max_length=32)
    gender = models.CharField(max_length=1, choices=GENDER)
    birthdate = models.DateField()
    country = CountryField()
    mugshot = models.ImageField(upload_to=mugshot_path)
    email = models.EmailField(null=True, default=None)

    class Meta:
        verbose_name = _("Person")
        verbose_name_plural = _("People")

    def __str__(self):
        return f"{self.nickname} ({self.firstname} {self.surname})"


class Team(models.Model):
    name = models.CharField(max_length=128, unique=True)
    logo = models.ImageField(upload_to=logo_path, null=True, default=None)

    class Meta:
        verbose_name = _("Team")
        verbose_name_plural = _("Teams")

    def __str__(self):
        return f"Team {self.name}"


class Championship(models.Model):
    ENDING_MODES = (
        ("CROSS_AFTER_TIME", "Cross Start/Finish Line after time"),
        ("CROSS_AFTER_LAPS", "Cross Start/Finish line after Nb laps"),
        ("QUALIFYING", "Qualifying - Best lap time before time elapses"),
        (
            "QUALIFYING_PLUS",
            "Qualifying+ - Best time crossing line, last lap starts after time",
        ),
        ("FULL_LAPS", "Full laps - Race ends when you complete set number of laps"),
        (
            "TIME_ONLY",
            "Time Only - Positions frozen at last crossing before time expired",
        ),
        ("AUTO_TRANSFORM", "Auto-transform to CROSS_AFTER_TIME when max time expires"),
    )

    QUALIFYING_TIEBREAKER_CHOICES = (
        ("FIRST_SET", "First to set the time"),
        ("BEST_TIMES", "Compare 2nd, 3rd, ... best times"),
    )

    name = models.CharField(max_length=128, unique=True)
    start = models.DateField()
    end = models.DateField()

    # Race ending mode configuration (LOCKED for all rounds in this championship)
    default_ending_mode = models.CharField(
        max_length=32,
        choices=ENDING_MODES,
        default="TIME_ONLY",
        verbose_name="Default Race Ending Mode",
    )
    default_lap_count = models.IntegerField(
        null=True, blank=True, verbose_name="Default Lap Count"
    )
    default_time_limit = models.DurationField(
        null=True, blank=True, verbose_name="Default Time Limit"
    )
    qualifying_tiebreaker = models.CharField(
        max_length=16,
        choices=QUALIFYING_TIEBREAKER_CHOICES,
        default="FIRST_SET",
        verbose_name="Qualifying Tiebreaker",
    )

    @property
    def ongoing(self):
        now = dt.date.today()
        return self.start <= now <= self.end

    class Meta:
        verbose_name = _("Championship")
        verbose_name_plural = _("Championships")

    def __str__(self):
        return f"{self.name}"


class Round(models.Model):
    # Instance-level lock for end_race operations
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not hasattr(self, "_end_race_lock"):
            self._end_race_lock = asyncio.Semaphore(1)

    LIMIT = (
        ("none", "No Time Limit"),
        ("race", "Race Time Limit "),
        ("session", "Session Time Limit"),
    )
    LMETHOD = (
        ("none", "--"),
        ("time", "Time in minutes"),
        ("percent", "Average + N percents"),
    )
    name = models.CharField(max_length=32)
    championship = models.ForeignKey(Championship, on_delete=models.CASCADE)
    start = models.DateTimeField()
    duration = models.DurationField()
    change_lanes = models.IntegerField(
        default=2, validators=[MinValueValidator(1), MaxValueValidator(4)]
    )
    pitlane_open_after = models.DurationField(default=dt.timedelta(minutes=10))
    pitlane_close_before = models.DurationField(default=dt.timedelta(minutes=10))
    limit_time = models.CharField(
        max_length=16,
        choices=LIMIT,
        default="race",
        verbose_name="Maximun Driving Time",
    )
    limit_method = models.CharField(
        max_length=16,
        choices=LMETHOD,
        default="percent",
        verbose_name="Maximun Driving Time Method",
    )
    limit_value = models.IntegerField(
        default=30, verbose_name="Maximun Driving Time Value"
    )
    required_changes = models.IntegerField(
        default=9, verbose_name="Required Driver Changes"
    )
    limit_time_min = models.DurationField(
        default=dt.timedelta(minutes=1),
        verbose_name="Minimum Driving Time",
    )
    weight_penalty = models.JSONField(
        default=default_weight_penalty,
        null=True,
        help_text="Weight penalty configuration in format: ['oper', [limit1, value1], [limit2, value2], ...]",
    )

    # Lap-based timing configuration (rounds can only adjust parameters, not change mode)
    uses_legacy_session_model = models.BooleanField(
        default=True,
        verbose_name="Use Legacy Session Model",
        help_text="True=time-only (legacy), False=lap-based timing",
    )
    lap_count_adjustment = models.IntegerField(
        null=True,
        blank=True,
        verbose_name="Lap Count Adjustment",
        help_text="Override championship default lap count for this round",
    )
    time_limit_adjustment = models.DurationField(
        null=True,
        blank=True,
        verbose_name="Time Limit Adjustment",
        help_text="Override championship default time limit for this round",
    )

    # No user serviceable parts below
    ready = models.BooleanField(default=False)
    started = models.DateTimeField(null=True, blank=True)
    ended = models.DateTimeField(null=True, blank=True)
    post_race_check_completed = models.BooleanField(default=False)
    qr_fernet = models.BinaryField(
        max_length=64, default=Fernet.generate_key, editable=False
    )

    @property
    def active_race(self):
        """Return the first unfinished race in sequence order, or None for legacy rounds."""
        if self.uses_legacy_session_model:
            return None
        return self.races.filter(ended__isnull=True).order_by("sequence_number").first()

    @property
    def ongoing(self):
        if self.started is None:
            return False
        if not self.ended:
            return True
        return False

    @property
    def time_paused(self):
        pass

    @property
    def is_paused(self):
        if self.started:
            return self.round_pause_set.filter(end__isnull=True).exists()
        return True

    @property
    def time_elapsed(self):
        # Calculate paused time within the session duration
        if not self.started:
            return dt.timedelta()
        now = dt.datetime.now()
        totalpause = dt.timedelta()
        for pause in self.round_pause_set.all():
            if pause.end is None:
                now = pause.start
            else:
                totalpause += pause.end - pause.start
        return now - self.started - totalpause

    @sync_to_async
    def async_time_elapsed(self):
        return self.time_elapsed

    @property
    def pit_lane_open(self):
        active = self.active_race
        if active is not None and active.race_type != "MAIN":
            return True
        elapsed = self.time_elapsed
        if elapsed < self.pitlane_open_after:
            return False
        if elapsed > self.duration - self.pitlane_close_before:
            return False
        return True

    @property
    def teams(self):
        """
        Returns a list of Team objects participating in this Round.
        """
        teams = Team.objects.filter(
            championship_team__round_team__round=self
        ).distinct()
        return list(teams)

    @property
    def current_session_info(self):
        """
        Returns a dictionary of active sessions for each team, with participants.
        """
        sessions = {}
        for team in self.teams:
            try:
                active_session = self.session_set.filter(
                    driver__team__team=team,
                    start__isnull=False,
                    end__isnull=True,
                ).latest("start")
                sessions[team.pk] = {
                    "participants": list(active_session.participants.all()),
                    "start_time": active_session.start,
                }
            except self.session_set.model.DoesNotExist:
                sessions[team.pk] = None
        return sessions

    def start_race(self):
        now = dt.datetime.now()
        sessions = self.session_set.filter(
            round=self, register__isnull=False, start__isnull=True, end__isnull=True
        )
        for session in sessions:
            session.start = now
            session.save()
        self.started = now
        self.save()

    def end_race(self):
        now = dt.datetime.now()
        print(f"Ending race at {now}.")
        sessions = self.session_set.filter(
            register__isnull=False, start__isnull=False, end__isnull=True
        )
        for session in sessions:
            session.end = now
            session.save()
        self.ended = now
        self.save()

        sessions = self.session_set.filter(
            round=self, register__isnull=False, start__isnull=True, end__isnull=True
        )
        for session in sessions:
            session.delete()
        ChangeLane.objects.all().delete()
        return self.post_race_check()

    def pause_race(self):
        now = dt.datetime.now()
        if self.round_pause_set.filter(round=self, end__isnull=True).exists():
            # There is an open round_pause, so don't pause
            return
        pause = round_pause.objects.create(
            start=now,
            round=self,
        )

    def restart_race(self):
        """
        Resets the 'end' attribute of the latest round_pause only if there are no open round_pauses.
        """

        latest_pause = (
            self.round_pause_set.filter(round=self, end__isnull=True)
            .order_by("-start")
            .first()
        )

        if latest_pause:
            latest_pause.end = dt.datetime.now()
            latest_pause.save()

    def false_start(self):
        sessions = self.session_set.filter(
            round=self, register__isnull=False, start__isnull=False, end__isnull=True
        )
        for session in sessions:
            session.start = None
            session.save()
        self.started = None
        self.save()

    def false_restart(self):
        """
        Resets the 'end' attribute of the latest round_pause only if there are no open round_pauses.
        """
        if self.round_pause_set.filter(end__isnull=True).exists():
            # There is an open round_pause, so don't reset
            return

        latest_pause = self.round_pause_set.order_by("-start").first()

        if latest_pause:
            latest_pause.end = None
            latest_pause.save()

    def pre_race_check(self, excluded_team_ids=None):
        """
        Checks that each team has exactly one driver with a registered but unstarted session,
        and that all drivers have a non-zero weight.

        Args:
            excluded_team_ids: set/list of round_team PKs to skip (e.g. eliminated teams)
        """
        errors = []
        excluded = set(excluded_team_ids) if excluded_team_ids else set()

        for round_team_instance in self.round_team_set.all():
            if round_team_instance.pk in excluded:
                continue

            drivers = round_team_instance.team_member_set.filter(driver=True)

            registered_drivers = []
            for driver in drivers:
                sessions = driver.session_set.filter(
                    register__isnull=False,
                    start__isnull=True,
                    end__isnull=True,
                )

                if sessions.exists():
                    registered_drivers.append(driver)

                if driver.weight <= 10:
                    errors.append(
                        f"Driver {driver.member.nickname} in team {round_team_instance.team.team.name} has an unlikely weight."
                    )

            if len(registered_drivers) != 1:
                errors.append(
                    f"Team {round_team_instance.team.team.name} ({round_team_instance.team.number}) has {len(registered_drivers)} registered to start. Expected 1."
                )

        if errors:
            return errors
        return None

    def activate_race_ready(self):
        """Set round ready and create change lanes. Call after all pre-checks pass."""
        self.ready = True
        self.save()
        for i in range(self.change_lanes):
            ChangeLane.objects.create(
                driver=None,
                round=self,
                lane=i + 1,
            )

    def post_race_check(self):
        """
        Create post-race penalties based on transgressions.
        Checks for required_changes, time_limit, and time_limit_min transgressions
        and creates RoundPenalty records for Post Race Laps penalties.
        """
        print(f"\n=== POST RACE CHECK STARTING for {self.name} ===")

        # Safety mechanism 1: Check if post-race check already completed
        if self.post_race_check_completed:
            print(
                f"⚠️ POST RACE CHECK ALREADY COMPLETED - SKIPPING to prevent duplicates"
            )
            return 0

        # Single timestamp for all penalties created in this check
        penalty_timestamp = dt.datetime.now()
        penalties_created = 0

        # Get championship and all relevant penalties at once
        championship = self.championship
        penalties = {}

        # Try to get all three penalties
        try:
            penalties["required_changes"] = ChampionshipPenalty.objects.get(
                championship=championship,
                penalty__name="required changes",
                sanction="P",  # Post Race Laps
            )
        except ChampionshipPenalty.DoesNotExist:
            penalties["required_changes"] = None

        try:
            penalties["time_limit"] = ChampionshipPenalty.objects.get(
                championship=championship,
                penalty__name="time limit",
                sanction="P",  # Post Race Laps
            )
        except ChampionshipPenalty.DoesNotExist:
            penalties["time_limit"] = None

        try:
            penalties["time_limit_min"] = ChampionshipPenalty.objects.get(
                championship=championship,
                penalty__name="time limit min",
                sanction="P",  # Post Race Laps
            )
        except ChampionshipPenalty.DoesNotExist:
            penalties["time_limit_min"] = None

        # If no penalties are configured, return early
        if not any(penalties.values()):
            return penalties_created

        # Calculate duration in hours once for per_hour penalties (as integer)
        duration_hours = self.duration.total_seconds() // 3600

        # Loop through all participating teams
        for team in self.round_team_set.all():
            # 1. Check team-level required_changes transgression
            if penalties["required_changes"]:
                transgression_count = team.required_changes_transgression
                if transgression_count > 0:
                    # Calculate penalty laps (ensure integer)
                    penalty_laps = (
                        penalties["required_changes"].value * transgression_count
                    )

                    # If penalty is per hour, multiply by race duration in hours
                    if penalties["required_changes"].option == "per_hour":
                        penalty_laps = penalty_laps * duration_hours

                    # Create RoundPenalty
                    round_penalty = RoundPenalty.objects.create(
                        round=self,
                        offender=team,
                        victim=None,  # Team penalties have no victim
                        penalty=penalties["required_changes"],
                        value=penalty_laps,
                        imposed=penalty_timestamp,
                    )
                    penalties_created += 1

            # 2. Loop through all drivers in this team
            print(f"\n--- Checking time limit violations for Team {team.number} ---")
            for driver in team.team_member_set.filter(driver=True):
                # Check driver-level time_limit transgression
                if penalties["time_limit"]:
                    # Get detailed info for logging
                    ltype, lval = self.driver_time_limit(team)
                    driver_time_spent = driver.time_spent
                    transgression_count = driver.limit_time_transgression

                    print(f"Driver {driver.member.nickname}:")
                    print(
                        f"  - Time spent: {driver_time_spent.total_seconds()/60:.1f} minutes"
                    )
                    print(
                        f"  - Time limit: {lval.total_seconds()/60:.1f} minutes ({ltype})"
                    )
                    print(f"  - Transgression count: {transgression_count}")

                    if transgression_count > 0:
                        print(f"  - ⚠️ VIOLATION DETECTED - Creating penalty")
                        # Calculate penalty laps (ensure integer)
                        penalty_laps = (
                            penalties["time_limit"].value * transgression_count
                        )

                        # If penalty is per hour, multiply by race duration in hours
                        if penalties["time_limit"].option == "per_hour":
                            penalty_laps = penalty_laps * duration_hours

                        print(f"  - Penalty laps: {penalty_laps}")

                        # Create RoundPenalty for the driver's team
                        round_penalty = RoundPenalty.objects.create(
                            round=self,
                            offender=team,
                            victim=None,  # Driver penalties are assigned to their team
                            penalty=penalties["time_limit"],
                            value=penalty_laps,
                            imposed=penalty_timestamp,
                        )
                        penalties_created += 1
                    else:
                        print(f"  - ✅ No violation")
                else:
                    print(
                        f"Driver {driver.member.nickname}: No time_limit penalty configured"
                    )

                # Check driver-level time_limit_min transgression
                if penalties["time_limit_min"]:
                    transgression_count = driver.limit_time_min_transgression
                    if transgression_count > 0:
                        # Calculate penalty laps (ensure integer)
                        penalty_laps = (
                            penalties["time_limit_min"].value * transgression_count
                        )

                        # If penalty is per hour, multiply by race duration in hours
                        if penalties["time_limit_min"].option == "per_hour":
                            penalty_laps = penalty_laps * duration_hours

                        # Create RoundPenalty for the driver's team
                        round_penalty = RoundPenalty.objects.create(
                            round=self,
                            offender=team,
                            victim=None,  # Driver penalties are assigned to their team
                            penalty=penalties["time_limit_min"],
                            value=penalty_laps,
                            imposed=penalty_timestamp,
                        )
                        penalties_created += 1

        # Mark post-race check as completed to prevent duplicates
        self.post_race_check_completed = True
        self.save()

        print(
            f"\n=== POST RACE CHECK COMPLETE - {penalties_created} penalties created ===\n"
        )
        return penalties_created

    def change_queue(self):
        sessions = self.session_set.filter(
            register__isnull=False, start__isnull=True, end__isnull=True
        ).order_by("register")
        return sessions

    def next_driver_change(self):
        if not self.pit_lane_open:
            return "close"
        # Get drivers currently in a ChangeLane
        drivers_in_lanes = ChangeLane.objects.filter(
            round=self, driver__isnull=False
        ).values_list("driver_id", flat=True)

        # Get the next session excluding those drivers
        session = (
            self.session_set.filter(
                register__isnull=False, start__isnull=True, end__isnull=True
            )
            .exclude(driver_id__in=drivers_in_lanes)
            .order_by("register")
            .first()
        )
        return session

    def driver_register(self, driver):
        """
        Creates a Session for the given driver and sets the registered time to now.
        """
        retval = {
            "message": f"This should not have happened!",
            "status": "error",
        }
        if self.started and not self.pit_lane_open:
            raise ValidationError("The pit lane is closed.")

        if not driver.driver:
            raise ValidationError(f"{driver.member.nickname} is not a driver.")

        now = dt.datetime.now()
        asession = self.session_set.filter(
            driver=driver, register__isnull=False, start__isnull=False, end__isnull=True
        ).first()
        if asession:
            return {
                "message": f"Driver {driver.member.nickname} from team {driver.team.number} is currently driving!",
                "status": "error",
            }
        #
        # Did we already register?
        pending_sessions = self.session_set.filter(
            register__isnull=False, start__isnull=True, end__isnull=True
        ).order_by("register")

        # Get the top self.change_lanes sessions
        top_sessions = pending_sessions[: self.change_lanes]

        session = self.session_set.filter(
            driver=driver, register__isnull=False, start__isnull=True, end__isnull=True
        ).first()
        if session:
            if self.started and session in top_sessions:
                return {
                    "message": f"Driver {driver.member.nickname} from team {driver.team.number} is due in pit lane. Cannot be removed.",
                    "status": "error",
                }
            else:
                session.delete()
                return {
                    "message": f"Driver {driver.member.nickname} from team {driver.team.number} was removed.",
                    "status": "warning",
                }
        else:
            session = Session.objects.create(
                driver=driver,
                round=self,
                register=now,
            )
            retval = {
                "message": f"Driver {driver.member.nickname} from team {driver.team.number} registered.",
                "status": "ok",
            }
        if self.started:
            alane = (
                ChangeLane.objects.filter(round=self, driver__isnull=True)
                .order_by("lane")
                .first()
            )
            if alane:
                alane.driver = driver
                alane.save()
        return retval

    def driver_endsession(self, driver):
        """
        Ends the given driver's session and starts the next driver's session on the same team.
        """

        retval = {
            "message": f"This should not have happened!",
            "status": "error",
        }
        now = dt.datetime.now()

        # 1. End the current driver's session
        try:
            current_session = driver.session_set.get(
                round=self,
                register__isnull=False,
                start__isnull=False,
                end__isnull=True,
            )
        except ObjectDoesNotExist:
            raise ValidationError(f"Driver {driver} has no current session.")
        except MultipleObjectsReturned:
            raise ValidationError(f"Driver {driver} has multiple current sessions.")

        # 2. Find and start the next driver's session
        try:
            related_team_members = team_member.objects.filter(team=driver.team)

            # Find the oldest active session among these team members
            next_session = (
                Session.objects.filter(
                    driver__in=related_team_members,
                    start__isnull=True,
                    end__isnull=True,
                )
                .order_by("register")
                .first()
            )

            if next_session:
                current_session.end = now
                current_session.save()
                next_session.start = now
                next_session.save()

                retval = {
                    "message": f"Driver {driver.member.nickname} from team {driver.team.number} ended session.",
                    "status": "ok",
                }
                # Update change lane
                alane = ChangeLane.objects.filter(
                    round=self, driver=next_session.driver
                ).first()
                if alane:
                    alane.next_driver()
                else:
                    print(f"Error: Could not find lane for {next_session.driver}")
            else:
                retval = {
                    "message": f"Keeo driving no one is waiting for teasm {driver.team.number}.",
                    "status": "error",
                }

        except ObjectDoesNotExist:
            # Driver is not associated with a round_team
            print(f"Driver {driver} is not associated with a round_team.")
            retval["message"] = f"Driver {driver} is not associated with a round_team."
        except MultipleObjectsReturned:
            # Driver is associated with multiple round_teams (unexpected)
            print(f"Driver {driver} is associated with multiple round_teams.")
            retval[
                "message"
            ] = f"Driver {driver} is associated with multiple round_teams."
        return retval

    def driver_time_limit(self, rteam):
        """
        For a team member, calculate the max time driving.
        Returns (limit_type, limit_timedelta) where limit_timedelta is always a timedelta.
        """
        if self.limit_time == "none":
            return None, None
        if self.limit_method == "none":
            return None, None
        if self.limit_method == "time":
            # Convert minutes to timedelta
            return self.limit_time, dt.timedelta(minutes=self.limit_value)
        elif self.limit_method == "percent":
            driver_count = team_member.objects.filter(team=rteam, driver=True).count()
            maxt = (self.duration / driver_count) * (1 + self.limit_value / 100)
            return self.limit_time, maxt  # maxt is already a timedelta
        return None, None

    def clean(self):
        super().clean()  # Call the parent class's clean method

        if self.weight_penalty:
            operatorok = False
            for arule in self.weight_penalty:
                if (
                    isinstance(arule, list)
                    and len(arule) == 2
                    and isinstance(arule[0], (int, float))
                    and isinstance(arule[1], (int, float))
                ):
                    continue
                if (
                    isinstance(arule, str)
                    and arule in [">=", "<=", ">", "<"]
                    and not operatorok
                ):
                    operatorok = True
                    continue
                raise ValidationError(
                    "Only one operator is allowed for weight penalty. All others must be numeric lists of the form [<weight limit>, <penalty>]"
                )
            if not operatorok:
                raise ValidationError(
                    "Weight penaly must have an operator in >=, <=, > or <"
                )

    def save(self, *args, **kwargs):
        if self.weight_penalty:
            rules = self.weight_penalty
            operator = None
            newrules = []
            for arule in rules:
                if isinstance(arule, list):
                    newrules.append(arule)
                else:
                    operator = arule.encode("ascii").decode()

            if operator in [">=", ">"]:
                newrules.sort(key=lambda item: item[0], reverse=True)
            else:
                newrules.sort(key=lambda item: item[0])

            # Reconstruct the list with the operator and sorted pairs
            self.weight_penalty = [operator] + newrules
        else:
            self.weight_penalty = None

        super().save(*args, **kwargs)

    class Meta:
        unique_together = ("championship", "name")
        verbose_name = _("Round")
        verbose_name_plural = _("Rounds")
        constraints = [
            models.CheckConstraint(
                check=models.Q(started__isnull=True) | models.Q(ready=True),
                name="started_requires_ready",
            ),
            models.CheckConstraint(
                check=models.Q(ended__isnull=True) | models.Q(started__isnull=False),
                name="ended_requires_started",
            ),
        ]

    def __str__(self):
        return f"{self.name} of {self.championship.name}"


class Race(models.Model):
    """
    Represents a single race within a Round.
    A Round can contain multiple races (e.g., Q1, Q2, Q3, Main).
    """

    RACE_TYPES = (
        ("Q1", "Qualifying 1"),
        ("Q2", "Qualifying 2"),
        ("Q3", "Qualifying 3"),
        ("MAIN", "Main Race"),
        ("PRACTICE", "Practice"),
    )

    START_MODES = (
        ("IMMEDIATE", "Immediate countdown"),
        ("FIRST_CROSSING", "Start on first passage"),
    )

    round = models.ForeignKey(Round, on_delete=models.CASCADE, related_name="races")
    race_type = models.CharField(max_length=16, choices=RACE_TYPES)
    sequence_number = models.IntegerField(
        verbose_name="Sequence Number",
        help_text="Order within round (1=first, 2=second, etc.)",
    )

    # Inherits mode from Championship, can override parameters
    ending_mode = models.CharField(
        max_length=32,
        choices=Championship.ENDING_MODES,
        verbose_name="Race Ending Mode",
    )
    lap_count_override = models.IntegerField(
        null=True, blank=True, verbose_name="Lap Count Override"
    )
    time_limit_override = models.DurationField(
        null=True, blank=True, verbose_name="Time Limit Override"
    )
    count_crossings_during_suspension = models.BooleanField(
        default=False, verbose_name="Count Crossings During Suspension"
    )

    start_mode = models.CharField(
        max_length=16,
        choices=START_MODES,
        default="IMMEDIATE",
        verbose_name="Start Mode",
    )

    # State (mirrors Round pattern)
    started = models.DateTimeField(null=True, blank=True)
    ended = models.DateTimeField(null=True, blank=True)
    ready = models.BooleanField(default=False)

    # Dependencies
    depends_on_race = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="dependent_races",
        verbose_name="Depends On Race",
    )
    grid_locked = models.BooleanField(default=False, verbose_name="Grid Locked")

    class Meta:
        verbose_name = _("Race")
        verbose_name_plural = _("Races")
        unique_together = ("round", "sequence_number")
        ordering = ["round", "sequence_number"]

    def __str__(self):
        return f"{self.get_race_type_display()} - {self.round.name}"

    # ---- properties used by timer_widget and signals ----

    @property
    def duration(self):
        """Effective time limit as timedelta (same interface as Round.duration)."""
        return self.get_effective_time_limit()

    @property
    def time_elapsed(self):
        """Wall-clock time minus pauses since this race started."""
        if not self.started:
            return dt.timedelta()
        now = dt.datetime.now()
        end = self.ended or now
        totalpause = dt.timedelta()
        for pause in self.round.round_pause_set.all():
            if pause.end is None:
                # Open pause — freeze clock at pause start
                end = min(self.ended or pause.start, pause.start)
            else:
                # Closed pause — count overlap with race window
                p_start = max(pause.start, self.started)
                p_end = min(pause.end, self.ended or now)
                if p_end > p_start:
                    totalpause += p_end - p_start
        return end - self.started - totalpause

    @property
    def is_paused(self):
        """Delegates to the parent round."""
        return self.round.is_paused

    @property
    def is_ready(self):
        """Alias for template consistency with Round."""
        return self.ready

    def get_effective_lap_count(self):
        """Get the effective lap count (override or round adjustment or championship default)"""
        if self.lap_count_override is not None:
            return self.lap_count_override
        if self.round.lap_count_adjustment is not None:
            return self.round.lap_count_adjustment
        return self.round.championship.default_lap_count or 0

    def get_effective_time_limit(self):
        """Get the effective time limit (override or round adjustment or championship default)"""
        if self.time_limit_override is not None:
            return self.time_limit_override
        if self.round.time_limit_adjustment is not None:
            return self.round.time_limit_adjustment
        return self.round.championship.default_time_limit or dt.timedelta(hours=4)

    def get_all_teams(self):
        """Get all teams registered for this race (including retired)"""
        return self.round.round_team_set.all()

    def get_participating_teams_count(self):
        """Get count of active (non-retired) teams in this race"""
        return self.round.round_team_set.filter(retired=False).count()

    def get_participating_teams(self):
        """Get active (non-retired) teams in this race"""
        return self.round.round_team_set.filter(retired=False)

    def is_race_finished(self):
        """Check if race ended based on configured mode"""
        if not self.started:
            return False

        mode_checkers = {
            "CROSS_AFTER_TIME": self._check_cross_after_time,
            "CROSS_AFTER_LAPS": self._check_cross_after_laps,
            "QUALIFYING": self._check_qualifying,
            "QUALIFYING_PLUS": self._check_qualifying_plus,
            "FULL_LAPS": self._check_full_laps,
            "TIME_ONLY": self._check_time_only,
            "AUTO_TRANSFORM": self._check_auto_transform,
        }
        checker = mode_checkers.get(self.ending_mode)
        if checker:
            return checker()
        return False

    def _check_cross_after_time(self):
        """Leader-based finish: leader must cross after time, then all active teams must cross."""
        time_limit = self.get_effective_time_limit()
        cutoff_time = self.started + time_limit

        if timezone.now() < cutoff_time:
            return False

        active_teams = self.get_participating_teams()
        if not active_teams.exists():
            return True

        # Find leader: most valid laps, then earliest last crossing time
        leader = None
        leader_laps = -1
        leader_last_crossing = None

        for team in active_teams:
            team_laps = self.lap_crossings.filter(team=team, is_valid=True).count()
            if team_laps > 0:
                last_crossing = (
                    self.lap_crossings.filter(team=team, is_valid=True)
                    .order_by("-crossing_time")
                    .first()
                    .crossing_time
                )
            else:
                last_crossing = None

            if team_laps > leader_laps or (
                team_laps == leader_laps
                and last_crossing is not None
                and (
                    leader_last_crossing is None or last_crossing < leader_last_crossing
                )
            ):
                leader = team
                leader_laps = team_laps
                leader_last_crossing = last_crossing

        if leader is None:
            return False

        # Leader must have crossed after cutoff
        leader_crossed_after = self.lap_crossings.filter(
            team=leader, crossing_time__gte=cutoff_time
        ).exists()
        if not leader_crossed_after:
            return False

        # All other active teams must also have crossed after cutoff
        teams_crossed_after = (
            self.lap_crossings.filter(crossing_time__gte=cutoff_time)
            .values_list("team_id", flat=True)
            .distinct()
        )

        return set(active_teams.values_list("id", flat=True)).issubset(
            set(teams_crossed_after)
        )

    def _check_cross_after_laps(self):
        """
        When first racer completes required laps and crosses line, THAT racer's race ends.
        Other racers' races end individually when THEY cross the line after completing laps.
        Race is finished when all racers have crossed after completing required laps.
        """
        required_laps = self.get_effective_lap_count()

        # Check if any team has completed required laps
        teams_completed = (
            self.lap_crossings.filter(lap_number__gte=required_laps, is_valid=True)
            .values_list("team_id", flat=True)
            .distinct()
        )

        if not teams_completed:
            return False  # No one has finished yet

        # Race is finished when all teams have crossed after completing laps
        return len(teams_completed) == self.get_participating_teams_count()

    def _check_qualifying(self):
        """Time elapsed - all laps that finish before time count"""
        time_limit = self.get_effective_time_limit()
        elapsed = timezone.now() - self.started
        return elapsed >= time_limit

    def _check_qualifying_plus(self):
        """
        Last lap that counts MUST have started before time expired
        but can finish after time (last start-finish crossing after time ran out).
        This is F1 qualifying style.
        """
        time_limit = self.get_effective_time_limit()
        cutoff_time = self.started + time_limit

        if timezone.now() < cutoff_time:
            return False  # Time hasn't expired yet

        # Find all teams that started a lap before cutoff but haven't finished it yet
        teams_still_on_final_lap = set()

        for team in self.get_participating_teams():
            last_crossing = (
                self.lap_crossings.filter(team=team, is_valid=True)
                .order_by("-crossing_time")
                .first()
            )

            if last_crossing and last_crossing.crossing_time < cutoff_time:
                # Started a lap before cutoff
                # Check if they've crossed since cutoff
                crossed_after_cutoff = self.lap_crossings.filter(
                    team=team, crossing_time__gt=cutoff_time, is_valid=True
                ).exists()

                if not crossed_after_cutoff:
                    teams_still_on_final_lap.add(team.id)

        # Race finished when all teams that started final lap have crossed
        return len(teams_still_on_final_lap) == 0

    def _check_full_laps(self):
        """All teams completed required laps"""
        required_laps = self.get_effective_lap_count()
        teams_finished = (
            self.lap_crossings.filter(lap_number=required_laps, is_valid=True)
            .values_list("team_id", flat=True)
            .distinct()
        )

        return len(teams_finished) == self.get_participating_teams_count()

    def _check_time_only(self):
        """Time limit reached - positions frozen at last crossing before time"""
        time_limit = self.get_effective_time_limit()
        elapsed = timezone.now() - self.started
        return elapsed >= time_limit

    def _check_auto_transform(self):
        """
        If time expired, transform to CROSS_AFTER_TIME.
        Otherwise check lap completion.
        """
        time_limit = self.get_effective_time_limit()
        elapsed = timezone.now() - self.started

        if elapsed < time_limit:
            # Still in lap-based mode
            required_laps = self.get_effective_lap_count()
            max_laps_result = (
                self.lap_crossings.filter(is_valid=True)
                .values("team")
                .annotate(max_lap=models.Max("lap_number"))
                .aggregate(models.Max("max_lap"))
            )
            max_laps = max_laps_result.get("max_lap__max")

            return max_laps and max_laps >= required_laps
        else:
            # Time expired, transform to CROSS_AFTER_TIME
            if self.ending_mode == "AUTO_TRANSFORM":
                self.ending_mode = "CROSS_AFTER_TIME"
                self.save()
            return self._check_cross_after_time()

    def get_qualifying_results(self, tiebreaker="FIRST_SET"):
        """
        Get qualifying results sorted by best lap time with tiebreaker.

        Args:
            tiebreaker: "FIRST_SET" — ties broken by who set the time first
                        "BEST_TIMES" — ties broken by comparing 2nd, 3rd, ... best times

        Returns list of tuples: [(team, sort_key), ...]
        sort_key is (lap_time, crossing_time) for FIRST_SET or [lap_time, ...] for BEST_TIMES.
        """
        NO_TIME = dt.timedelta(hours=99)
        results = []
        for team in self.get_all_teams():
            crossings = self.lap_crossings.filter(
                team=team, is_valid=True, lap_time__isnull=False
            )
            if not crossings.exists():
                if tiebreaker == "FIRST_SET":
                    sort_key = (NO_TIME, dt.datetime.max)
                else:
                    sort_key = [NO_TIME]
                results.append((team, sort_key))
                continue

            if tiebreaker == "FIRST_SET":
                best = crossings.order_by("lap_time", "crossing_time").first()
                sort_key = (best.lap_time, best.crossing_time)
            else:  # BEST_TIMES
                sort_key = list(
                    crossings.order_by("lap_time").values_list("lap_time", flat=True)
                )
            results.append((team, sort_key))

        results.sort(key=lambda x: x[1])
        return results

    def process_qualifying_knockout(self):
        """
        Process qualifying knockout rules for this race.
        Applies all knockout rules to set grid positions for dependent races.
        """
        if self.race_type not in ["Q1", "Q2", "Q3"]:
            return  # Only qualifying races have knockout rules

        tiebreaker = self.round.championship.qualifying_tiebreaker
        results = self.get_qualifying_results(tiebreaker=tiebreaker)

        for rule in self.knockout_rules.all():
            # Get eliminated teams based on position range
            # Negative indices mean from end (e.g., -5 = bottom 5)
            start_idx = rule.eliminates_to_position_range_start
            end_idx = rule.eliminates_to_position_range_end

            if start_idx < 0 and end_idx < 0:
                # Both negative - slice from end
                eliminated = results[start_idx : end_idx + 1 if end_idx != -1 else None]
            else:
                # Positive indices
                eliminated = results[start_idx : end_idx + 1]

            # Set grid positions for target race
            for idx, (team, _) in enumerate(eliminated):
                GridPosition.objects.update_or_create(
                    race=rule.sets_grid_positions_for,
                    team=team,
                    defaults={
                        "position": rule.grid_position_offset + idx + 1,
                        "source": "KNOCKOUT",
                        "source_race": self,
                        "manually_overridden": False,
                    },
                )

    @staticmethod
    def combine_qualifying_results(qualifying_races, main_race, tiebreaker="FIRST_SET"):
        """
        Combine results from multiple qualifying races to set grid for main race.
        Only assigns positions to teams that are NOT already placed via KNOCKOUT.

        Args:
            qualifying_races: QuerySet/list of Race objects (Q1, Q2, Q3, etc.)
            main_race: Race object to set grid positions for
            tiebreaker: "FIRST_SET" or "BEST_TIMES"
        """
        # Teams already eliminated via knockout — skip them
        knockout_team_ids = set(
            GridPosition.objects.filter(race=main_race, source="KNOCKOUT").values_list(
                "team_id", flat=True
            )
        )

        combined = {}  # team -> list of (lap_time, crossing_time) or list of lap_times

        for race in qualifying_races:
            crossings = race.lap_crossings.filter(is_valid=True, lap_time__isnull=False)
            for team in race.get_all_teams():
                if team.pk in knockout_team_ids:
                    continue
                team_crossings = crossings.filter(team=team)
                if not team_crossings.exists():
                    continue

                if tiebreaker == "FIRST_SET":
                    best = team_crossings.order_by("lap_time", "crossing_time").first()
                    prev = combined.get(team)
                    if prev is None or (best.lap_time, best.crossing_time) < prev:
                        combined[team] = (best.lap_time, best.crossing_time)
                else:  # BEST_TIMES
                    lap_times = list(team_crossings.values_list("lap_time", flat=True))
                    combined.setdefault(team, []).extend(lap_times)

        # Build final sort keys
        if tiebreaker == "FIRST_SET":
            final = [(team, sort_key) for team, sort_key in combined.items()]
        else:  # BEST_TIMES
            final = [(team, sorted(lap_times)) for team, lap_times in combined.items()]

        final.sort(key=lambda x: x[1])

        # Clear previous COMBINED_Q positions (safe to re-run after each Q-race)
        GridPosition.objects.filter(race=main_race, source="COMBINED_Q").delete()

        # Start positions after any existing knockout positions
        knockout_max = (
            GridPosition.objects.filter(race=main_race, source="KNOCKOUT")
            .aggregate(models.Max("position"))
            .get("position__max")
            or 0
        )

        # Assign grid positions
        for idx, (team, _) in enumerate(final):
            position = knockout_max + idx + 1
            GridPosition.objects.create(
                race=main_race,
                team=team,
                position=position,
                source="COMBINED_Q",
                manually_overridden=False,
            )

    def auto_assign_grid_positions(self, source_type="CHAMPIONSHIP"):
        """
        Auto-assign grid positions based on source.

        Args:
            source_type: "CHAMPIONSHIP" (championship standings) or "QUALIFYING" (from depends_on_race)
        """
        if self.grid_locked:
            return  # Grid is locked, cannot auto-assign

        if source_type == "QUALIFYING" and self.depends_on_race:
            # Use qualifying race results
            results = self.depends_on_race.get_qualifying_results()
            for position, (team, _) in enumerate(results, 1):
                GridPosition.objects.update_or_create(
                    race=self,
                    team=team,
                    defaults={
                        "position": position,
                        "source": "QUALIFYING",
                        "source_race": self.depends_on_race,
                        "manually_overridden": False,
                    },
                )
        elif source_type == "CHAMPIONSHIP":
            # Use championship standings (placeholder - would need championship_team ordering)
            teams = list(self.get_all_teams())
            for position, team in enumerate(teams, 1):
                GridPosition.objects.update_or_create(
                    race=self,
                    team=team,
                    defaults={
                        "position": position,
                        "source": "CHAMPIONSHIP",
                        "manually_overridden": False,
                    },
                )

    def lock_grid(self):
        """Lock grid positions to prevent further auto-assignment"""
        self.grid_locked = True
        self.save()

    def unlock_grid(self):
        """Unlock grid positions to allow auto-assignment"""
        self.grid_locked = False
        self.save()

    def clone_transponder_assignments_from(self, source_race):
        """Bulk-create transponder assignments from another race."""
        source_assignments = RaceTransponderAssignment.objects.filter(race=source_race)
        new_assignments = []
        for a in source_assignments:
            new_assignments.append(
                RaceTransponderAssignment(
                    race=self,
                    transponder=a.transponder,
                    team=a.team,
                    kart_number=a.kart_number,
                    confirmed=a.confirmed,
                )
            )
        if new_assignments:
            RaceTransponderAssignment.objects.bulk_create(
                new_assignments, ignore_conflicts=True
            )

    def reset_grid_to_auto(self):
        """Reset grid to auto-assigned positions (remove manual overrides)"""
        if self.grid_locked:
            return

        # Delete all grid positions and re-auto-assign
        GridPosition.objects.filter(race=self).delete()

        if self.depends_on_race:
            self.auto_assign_grid_positions(source_type="QUALIFYING")
        else:
            self.auto_assign_grid_positions(source_type="CHAMPIONSHIP")

    def end_this_race(self):
        """End this race and handle qualifying results / round close-out.

        Model-level equivalent of the endofrace view, used by automated
        logic (e.g. all drivers crossing the line after time expires).
        Saving race.ended triggers the post_save signal which pushes a
        round_update to the race control WebSocket automatically.
        """
        now = dt.datetime.now()
        self.ended = now
        self.save(update_fields=["ended"])

        cround = self.round

        for session in cround.session_set.filter(
            register__isnull=False, start__isnull=False, end__isnull=True
        ):
            session.end = now
            session.save()

        cround.session_set.filter(
            register__isnull=False, start__isnull=True, end__isnull=True
        ).delete()

        ChangeLane.objects.all().delete()

        if self.race_type.startswith("Q"):
            tiebreaker = cround.championship.qualifying_tiebreaker
            main_race = cround.races.filter(race_type="MAIN").first()

            if self.knockout_rules.exists():
                self.process_qualifying_knockout()

            if main_race:
                ended_q_races = cround.races.filter(
                    race_type__startswith="Q", ended__isnull=False
                )
                Race.combine_qualifying_results(
                    ended_q_races, main_race, tiebreaker=tiebreaker
                )

        if cround.active_race is None:
            cround.ended = now
            cround.save()
            cround.post_race_check()

    def calculate_race_standings(self):
        """
        Calculate current race standings.
        Returns list of dicts with team info, laps, times, positions, and gaps.
        """
        if not self.started:
            return []

        def fmt_time(td):
            """Format timedelta as MM:SS.mmm"""
            if td is None:
                return "—"
            total_ms = int(td.total_seconds() * 1000)
            ms = total_ms % 1000
            total_s = total_ms // 1000
            s = total_s % 60
            m = total_s // 60
            return f"{m:02d}:{s:02d}.{ms:03d}"

        is_qualifying = self.race_type != "MAIN"

        standings = []
        for team in self.get_all_teams():
            # Get all valid lap crossings for this team
            laps = self.lap_crossings.filter(team=team, is_valid=True).order_by(
                "crossing_time"
            )

            if laps.exists():
                # Every valid crossing after the first is a completed lap.
                # count()-1 avoids undercounting when lap_time=None on a crossing
                # due to identical consecutive raw_times (decoder precision issue).
                laps_completed = max(0, laps.count() - 1)
                last_crossing = laps.last()
                total_time = last_crossing.crossing_time - self.started
                last_lap_time = last_crossing.lap_time
                best_lap = (
                    laps.filter(lap_time__isnull=False).order_by("lap_time").first()
                )
                best_lap_time = best_lap.lap_time if best_lap else None
            else:
                laps_completed = 0
                total_time = None
                last_lap_time = None
                best_lap_time = None

            # Get grid position if available
            try:
                grid_pos = GridPosition.objects.get(race=self, team=team)
                starting_position = grid_pos.position
            except GridPosition.DoesNotExist:
                starting_position = None

            standings.append(
                {
                    "team_id": team.id,
                    "team_number": team.number,
                    "team_name": team.name,
                    "retired": team.retired,
                    "laps_completed": laps_completed,
                    "total_time": total_time.total_seconds() if total_time else None,
                    "total_time_formatted": fmt_time(total_time),
                    "last_lap_time": last_lap_time.total_seconds()
                    if last_lap_time
                    else None,
                    "last_lap_time_formatted": fmt_time(last_lap_time),
                    "best_lap_time": best_lap_time.total_seconds()
                    if best_lap_time
                    else None,
                    "best_lap_time_formatted": fmt_time(best_lap_time),
                    "starting_position": starting_position,
                }
            )

        if is_qualifying:
            # Sort by best lap time ascending (no time = last)
            standings.sort(
                key=lambda x: (
                    x["best_lap_time"]
                    if x["best_lap_time"] is not None
                    else float("inf"),
                )
            )
        else:
            # Sort by laps (desc), then total time (asc)
            standings.sort(
                key=lambda x: (
                    -x["laps_completed"],
                    x["total_time"] if x["total_time"] is not None else float("inf"),
                )
            )

        # Add positions and gaps
        for idx, standing in enumerate(standings, 1):
            standing["position"] = idx

            if idx == 1:
                standing["gap_ahead"] = "—"
                standing["position_change"] = 0
            else:
                car_ahead = standings[idx - 2]
                if is_qualifying:
                    if standing["best_lap_time"] and car_ahead["best_lap_time"]:
                        diff = standing["best_lap_time"] - car_ahead["best_lap_time"]
                        standing["gap_ahead"] = f"+{diff:.3f}s"
                    else:
                        standing["gap_ahead"] = "—"
                    standing["position_change"] = 0
                else:
                    if standing["laps_completed"] < car_ahead["laps_completed"]:
                        lap_diff = (
                            car_ahead["laps_completed"] - standing["laps_completed"]
                        )
                        standing[
                            "gap_ahead"
                        ] = f"-{lap_diff} lap{'s' if lap_diff > 1 else ''}"
                    elif standing["total_time"] and car_ahead["total_time"]:
                        time_diff = standing["total_time"] - car_ahead["total_time"]
                        standing["gap_ahead"] = f"+{time_diff:.3f}s"
                    else:
                        standing["gap_ahead"] = "—"

                    if standing["starting_position"]:
                        standing["position_change"] = (
                            standing["starting_position"] - standing["position"]
                        )
                    else:
                        standing["position_change"] = 0

        return standings


class round_pause(models.Model):
    round = models.ForeignKey(Round, on_delete=models.CASCADE)
    start = models.DateTimeField(default=dt.datetime.now)
    end = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = _("Pause")
        verbose_name_plural = _("Pauses")

    def __str__(self):
        return f"{self.round.name} pause"


class championship_team(models.Model):
    championship = models.ForeignKey(Championship, on_delete=models.CASCADE)
    team = models.ForeignKey(Team, on_delete=models.CASCADE)
    number = models.IntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(99)]
    )

    class Meta:
        unique_together = (("championship", "number"), ("championship", "team"))
        verbose_name = _("Championship Team")
        verbose_name_plural = _("Championship Teams")

    def __str__(self):
        return f"({self.number}) {self.team.name} in {self.championship.name}."


class round_team(models.Model):
    round = models.ForeignKey(Round, on_delete=models.CASCADE)
    team = models.ForeignKey(championship_team, on_delete=models.CASCADE)
    retired = models.BooleanField(default=False)

    class Meta:
        unique_together = ("round", "team")
        verbose_name = _("Participating Team")
        verbose_name_plural = _("Participating Teams")
        ordering = ["team__number"]

    @property
    def name(self):
        return self.team.team.name

    @property
    def number(self):
        return self.team.number

    def __str__(self):
        return f"{self.team} in {self.round}"

    @property
    def required_changes_transgression(self):
        sess_count = (
            Session.objects.filter(driver__team=self, end__isnull=False)
            .filter(Q(race__race_type="MAIN") | Q(race__isnull=True))
            .count()
        )
        if sess_count <= self.round.required_changes:
            return 1 + self.round.required_changes - sess_count
        return 0

    @property
    def has_transgression(self):
        if self.required_changes_transgression:
            return True
        all_drivers = team_member.objects.filter(team=self, driver=True)
        for driver in all_drivers:
            if driver.has_transgression:
                return True
        return False


class team_member(models.Model):
    team = models.ForeignKey(round_team, on_delete=models.CASCADE)
    member = models.ForeignKey(Person, on_delete=models.CASCADE)
    driver = models.BooleanField(default=True)
    manager = models.BooleanField(default=False)
    weight = models.FloatField(default=0)

    def clean(self):
        super().clean()
        if self.manager:
            count = (
                team_member.objects.filter(team=self.team, manager=True)
                .exclude(pk=self.pk)
                .count()
            )
            if count > 0:
                raise ValidationError("Only one manager allowed per round and team.")
        # Custom validation for unique member per round
        existing_member_teams = team_member.objects.filter(
            member=self.member, team__round=self.team.round
        ).exclude(
            pk=self.pk
        )  # exclude the current object.

        if existing_member_teams.exists():
            raise ValidationError(
                "A person can only be a member of one team per round."
            )

    @property
    def time_spent(self):
        sessions = self.session_set.filter(driver=self, start__isnull=False).filter(
            Q(race__race_type="MAIN") | Q(race__isnull=True)
        )
        total_time = dt.timedelta(0)
        now = dt.datetime.now()
        for session in sessions:
            if session.end:
                session_time = session.end - session.start
            else:
                session_time = now - session.start
            paused_time = dt.timedelta(0)

            # Calculate paused time within the session duration
            if session.end:
                pauses = self.team.round.round_pause_set.filter(
                    start__lte=session.end,
                    end__gte=session.start,
                )
            else:
                pauses = self.team.round.round_pause_set.filter(
                    Q(start__lte=now), Q(end__gte=session.start) | Q(end__isnull=True)
                )

            for pause in pauses:
                pause_start = max(pause.start, session.start)
                pause_end = min(
                    pause.end or now, session.end or now
                )  # if pause.end is null, use now.
                paused_time += pause_end - pause_start

            total_time += session_time - paused_time
        return total_time

    @property
    def current_session(self):
        total_time = dt.timedelta(0)
        try:
            sessions = self.session_set.filter(
                driver=self, start__isnull=False, end__isnull=True
            )
            now = dt.datetime.now()
            for session in sessions:
                session_time = now - session.start
                paused_time = dt.timedelta(0)

                # Calculate paused time within the session duration

                pauses = self.team.round.round_pause_set.filter(
                    Q(start__lte=now), Q(end__gte=session.start) | Q(end__isnull=True)
                )

                for pause in pauses:
                    pause_start = max(pause.start, session.start)
                    pause_end = pause.end or now  # if pause.end is null, use now.
                    paused_time += pause_end - pause_start

                total_time += session_time - paused_time
                return total_time
        except ObjectDoesNotExist:
            # Handle the case where no session is found
            pass
        except MultipleObjectsReturned:
            _log.critical("There should be only one active session per team/driver")
        except Exception as e:
            _log.critical(f"Active session exception: {e}")
        finally:
            return total_time

    @property
    def ontrack(self):
        return self.session_set.filter(
            driver=self, start__isnull=False, end__isnull=True
        ).exists()

    @property
    def isready(self):
        return self.session_set.filter(driver=self, end__isnull=True).exists()

    def save(self, *args, **kwargs):
        self.clean()
        super().save(*args, **kwargs)

    class Meta:
        unique_together = ("team", "member")
        verbose_name = _("Team Member")
        verbose_name_plural = _("Team Members")
        ordering = ["id"]

    def __str__(self):
        return f"{self.member.nickname} for {self.team.team} in {self.team.round}"

    @property
    def weight_penalty(self):
        rules = self.team.round.weight_penalty
        if not rules:
            return None
        oper = rules[0]
        rules = rules[1:]
        if oper == ">":
            checkme = lambda x, y: x > y
        elif oper == ">=":
            checkme = lambda x, y: x >= y
        elif oper == "<":
            checkme = lambda x, y: x < y
        else:
            checkme = lambda x, y: x <= y

        for l, v in rules:
            if checkme(self.weight, l):
                return v

    @property
    def limit_time_transgression(self):
        cround = self.team.round
        did_transgress = 0
        ltype, lval = cround.driver_time_limit(self.team)
        time_spent = self.time_spent
        if ltype == "session":
            all_sessions = Session.objects.filter(driver=self)
            for session in all_sessions:
                if session.duration > lval:
                    did_transgress += 1
        elif ltype == "race":
            did_transgress = 1 if lval < time_spent else 0
        return did_transgress

    @property
    def limit_time_min_transgression(self):
        cround = self.team.round
        time_spent = self.time_spent
        if time_spent < cround.limit_time_min:
            return 1
        return 0

    @property
    def has_transgression(self):
        if self.limit_time_transgression:
            return True

        if self.limit_time_min_transgression:
            return True
        return False


class Session(models.Model):
    round = models.ForeignKey(Round, on_delete=models.CASCADE)
    driver = models.ForeignKey(team_member, on_delete=models.CASCADE)
    register = models.DateTimeField(default=dt.datetime.now)
    start = models.DateTimeField(null=True, blank=True)
    end = models.DateTimeField(null=True, blank=True)

    # Link to specific race within round (for lap-based timing)
    race = models.ForeignKey(
        Race, null=True, blank=True, on_delete=models.CASCADE, verbose_name="Race"
    )

    class Meta:
        verbose_name = _("Session")
        verbose_name_plural = _("Sessions")

    def __str__(self):
        return f"{self.driver.member.nickname} in {self.round}"

    @property
    def duration(self):
        total_time = dt.timedelta(0)
        now = dt.datetime.now()
        if self.end:
            session_time = self.end - self.start
        else:
            session_time = now - self.start
        paused_time = dt.timedelta(0)

        # Calculate paused time within the session duration
        if self.end:
            pauses = self.round.round_pause_set.filter(
                start__lte=self.end,
                end__gte=self.start,
            )
        else:
            pauses = self.round.round_pause_set.filter(
                Q(start__lte=now), Q(end__gte=self.start) | Q(end__isnull=True)
            )

        for pause in pauses:
            pause_start = max(pause.start, self.start)
            pause_end = min(
                pause.end or now, self.end or now
            )  # if pause.end is null, use now.
            paused_time += pause_end - pause_start

        total_time += session_time - paused_time
        return total_time


class Transponder(models.Model):
    """Hardware transponder registration"""

    transponder_id = models.CharField(
        max_length=32, unique=True, verbose_name="Transponder ID"
    )
    description = models.CharField(
        max_length=128, blank=True, verbose_name="Description"
    )
    active = models.BooleanField(default=True, verbose_name="Active")
    last_seen = models.DateTimeField(null=True, blank=True, verbose_name="Last Seen")

    class Meta:
        verbose_name = _("Transponder")
        verbose_name_plural = _("Transponders")

    def __str__(self):
        return f"Transponder {self.transponder_id}"


class RaceTransponderAssignment(models.Model):
    """Matching phase: transponder → team/kart"""

    race = models.ForeignKey(
        Race, on_delete=models.CASCADE, related_name="transponder_assignments"
    )
    transponder = models.ForeignKey(Transponder, on_delete=models.CASCADE)
    team = models.ForeignKey("round_team", on_delete=models.CASCADE)
    kart_number = models.IntegerField(
        null=True,
        blank=True,
        validators=[MinValueValidator(1), MaxValueValidator(99)],
        verbose_name="Kart Number",
    )
    confirmed = models.BooleanField(default=False, verbose_name="Confirmed")
    assigned_at = models.DateTimeField(auto_now_add=True, verbose_name="Assigned At")

    class Meta:
        verbose_name = _("Race Transponder Assignment")
        verbose_name_plural = _("Race Transponder Assignments")
        unique_together = [
            ("race", "transponder"),
        ]

    def __str__(self):
        return f"{self.transponder.transponder_id} → Team {self.team} (Kart #{self.kart_number})"


class LapCrossing(models.Model):
    """Core lap timing data - records each finish line crossing"""

    race = models.ForeignKey(
        Race, on_delete=models.CASCADE, related_name="lap_crossings"
    )
    team = models.ForeignKey("round_team", on_delete=models.CASCADE)
    transponder = models.ForeignKey(
        Transponder, on_delete=models.CASCADE, null=True, blank=True
    )

    # Lap timing data
    lap_number = models.IntegerField(
        validators=[MinValueValidator(1)], verbose_name="Lap Number"
    )
    crossing_time = models.DateTimeField(verbose_name="Crossing Time")
    lap_time = models.DurationField(null=True, blank=True, verbose_name="Lap Time")
    raw_time = models.FloatField(null=True, blank=True, verbose_name="Decoder Raw Time")
    message_id = models.UUIDField(
        null=True, blank=True, unique=True, verbose_name="Message ID"
    )

    # Lap status
    is_valid = models.BooleanField(default=True, verbose_name="Valid")
    is_suspicious = models.BooleanField(default=False, verbose_name="Suspicious")
    was_split = models.BooleanField(default=False, verbose_name="Was Split")
    split_from = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="split_laps",
        verbose_name="Split From",
    )
    counted_during_suspension = models.BooleanField(
        default=False, verbose_name="Counted During Suspension"
    )
    session = models.ForeignKey(
        Session, null=True, blank=True, on_delete=models.SET_NULL
    )

    class Meta:
        verbose_name = _("Lap Crossing")
        verbose_name_plural = _("Lap Crossings")
        ordering = ["race", "team", "lap_number"]
        indexes = [
            models.Index(fields=["race", "team", "lap_number"]),
            models.Index(fields=["race", "crossing_time"]),
            models.Index(fields=["is_suspicious"]),
            models.Index(fields=["transponder", "crossing_time"]),
        ]

    def __str__(self):
        return f"Lap {self.lap_number} - Team {self.team} @ {self.crossing_time}"


class GridPosition(models.Model):
    """Starting positions for races"""

    AUTO_SOURCES = (
        ("QUALIFYING", "From Qualifying Result"),
        ("COMBINED_Q", "From Combined Qualifying Results"),
        ("KNOCKOUT", "From Knockout Qualifying"),
        ("CHAMPIONSHIP", "From Championship Standings"),
        ("MANUAL", "Manually Assigned"),
    )

    race = models.ForeignKey(
        Race, on_delete=models.CASCADE, related_name="grid_positions"
    )
    team = models.ForeignKey("round_team", on_delete=models.CASCADE)
    position = models.IntegerField(
        validators=[MinValueValidator(1)], verbose_name="Grid Position"
    )

    # Position source tracking
    source = models.CharField(
        max_length=32, choices=AUTO_SOURCES, default="MANUAL", verbose_name="Source"
    )
    source_race = models.ForeignKey(
        Race,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="grid_source_for",
        verbose_name="Source Race",
    )

    # Override capability
    manually_overridden = models.BooleanField(
        default=False, verbose_name="Manually Overridden"
    )
    override_reason = models.TextField(blank=True, verbose_name="Override Reason")

    class Meta:
        verbose_name = _("Grid Position")
        verbose_name_plural = _("Grid Positions")
        unique_together = [
            ("race", "team"),
            ("race", "position"),
        ]
        ordering = ["race", "position"]

    def __str__(self):
        return f"P{self.position} - Team {self.team}"


class QualifyingKnockoutRule(models.Model):
    """Complex qualifying logic - knockout rules"""

    qualifying_race = models.ForeignKey(
        Race,
        on_delete=models.CASCADE,
        related_name="knockout_rules",
        verbose_name="Qualifying Race",
    )
    eliminates_to_position_range_start = models.IntegerField(
        verbose_name="Eliminate From Position", help_text="e.g., -5 for bottom 5 teams"
    )
    eliminates_to_position_range_end = models.IntegerField(
        verbose_name="Eliminate To Position", help_text="e.g., -1 for last team"
    )

    # What happens to eliminated teams
    sets_grid_positions_for = models.ForeignKey(
        Race,
        on_delete=models.CASCADE,
        related_name="knockout_sources",
        verbose_name="Sets Grid For Race",
    )
    grid_position_offset = models.IntegerField(
        default=0,
        verbose_name="Grid Position Offset",
        help_text="Where to place them in main race grid",
    )

    class Meta:
        verbose_name = _("Qualifying Knockout Rule")
        verbose_name_plural = _("Qualifying Knockout Rules")
        ordering = ["qualifying_race", "eliminates_to_position_range_start"]

    def __str__(self):
        return f"{self.qualifying_race} → {self.sets_grid_positions_for} (positions {self.eliminates_to_position_range_start} to {self.eliminates_to_position_range_end})"


class ChangeLane(models.Model):
    round = models.ForeignKey(Round, on_delete=models.CASCADE)
    lane = models.IntegerField(validators=[MinValueValidator(1), MaxValueValidator(4)])
    driver = models.ForeignKey(
        team_member, null=True, blank=True, on_delete=models.SET_NULL
    )
    open = models.BooleanField(default=False)

    def next_driver(self):
        sess = self.round.next_driver_change()
        print(f"Next driver from {sess}")
        if sess == "close":
            self.open = False
            self.driver = None
        elif sess:
            self.driver = sess.driver
        else:
            self.driver = None
        self.save()

    class Meta:
        unique_together = ("round", "lane")
        constraints = [
            UniqueConstraint(
                fields=["driver"],
                condition=Q(driver__isnull=False),
                name="unique_driver_when_not_null",
            )
        ]

    def __str__(self):
        return f"{self.round.name} Lane {self.lane}"


class Penalty(models.Model):
    name = models.CharField(max_length=32, unique=True)
    description = models.CharField(max_length=256)
    illustration = models.ImageField(upload_to=illustration_path, null=True, blank=True)

    class Meta:
        verbose_name = _("Penalty")
        verbose_name_plural = _("Penalties")

    def __str__(self):
        return self.name


class ChampionshipPenalty(models.Model):
    PTYPE = (
        ("S", "Stop & Go"),
        ("D", "Self Stop & Go"),
        ("L", "Laps"),
        ("P", "Post Race Laps"),
    )
    OPTION_CHOICES = (
        ("fixed", "Fixed"),
        ("variable", "Variable"),
        ("per_hour", "Per Hour"),
    )
    championship = models.ForeignKey(Championship, on_delete=models.CASCADE)
    penalty = models.ForeignKey(Penalty, on_delete=models.CASCADE)
    sanction = models.CharField(max_length=1, choices=PTYPE)
    value = models.IntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(120)], default=20
    )
    option = models.CharField(
        max_length=10, choices=OPTION_CHOICES, default="fixed", verbose_name="Option"
    )

    class Meta:
        unique_together = ("championship", "penalty")
        verbose_name = _("Championship Penalty")
        verbose_name_plural = _("Championship Penalties")

    def __str__(self):
        return f"{self.penalty.name} in {self.championship.name}"


class RoundPenalty(models.Model):
    round = models.ForeignKey(Round, on_delete=models.CASCADE)
    offender = models.ForeignKey(
        round_team, on_delete=models.CASCADE, related_name="offender_penalties"
    )
    victim = models.ForeignKey(
        round_team,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="victim_penalties",
    )
    penalty = models.ForeignKey(ChampionshipPenalty, on_delete=models.CASCADE)
    value = models.IntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(120)],
        help_text="Penalty value at the time of imposition",
    )
    imposed = models.DateTimeField()
    served = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = _("Round Penalty")
        verbose_name_plural = _("Round Penalties")

    def __str__(self):
        return f"{self.penalty.penalty.name} ({self.value}) for {self.offender}"


class PenaltyQueue(models.Model):
    """
    Queue for Stop & Go penalties to handle multiple penalties in sequence.
    Only Stop & Go ('S') and Self Stop & Go ('D') penalties can be queued.
    Ordered by timestamp, oldest first.
    """

    round_penalty = models.OneToOneField(
        RoundPenalty, on_delete=models.CASCADE, related_name="penalty_queue"
    )
    timestamp = models.DateTimeField(default=dt.datetime.now)

    class Meta:
        verbose_name = _("Penalty Queue Entry")
        verbose_name_plural = _("Penalty Queue Entries")
        ordering = ["timestamp"]  # Oldest first

    def clean(self):
        """Validate that only Stop & Go penalties can be queued"""
        if self.round_penalty and self.round_penalty.penalty.sanction not in ["S", "D"]:
            raise ValidationError(
                "Only Stop & Go ('S') and Self Stop & Go ('D') penalties can be queued."
            )

    def save(self, *args, **kwargs):
        self.clean()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"Queue: {self.round_penalty} at {self.timestamp}"

    @classmethod
    def get_next_penalty(cls, round_id):
        """Get the next penalty in queue for a given round"""
        return cls.objects.filter(round_penalty__round_id=round_id).first()

    @classmethod
    async def aget_next_penalty(cls, round_id):
        """Async version of get_next_penalty"""
        return await cls.objects.filter(round_penalty__round_id=round_id).afirst()

    def delay_penalty(self):
        """Move this penalty to the end of the queue"""
        self.timestamp = dt.datetime.now()
        self.save()

    @sync_to_async
    def adelay_penalty(self):
        """Async version of delay_penalty"""
        return self.delay_penalty()


class Logo(models.Model):
    name = models.CharField(max_length=128)
    image = models.ImageField(upload_to=logo_path)
    championship = models.ForeignKey(
        Championship, on_delete=models.CASCADE, null=True, blank=True
    )

    class Meta:
        verbose_name = _("Logo")
        verbose_name_plural = _("Logos")
        constraints = [
            models.UniqueConstraint(
                fields=["name", "championship"],
                condition=models.Q(name="organiser logo"),
                name="unique_organiser_logo_per_championship",
            )
        ]

    def __str__(self):
        return self.name
