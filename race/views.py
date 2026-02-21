# -*- encoding: utf-8 -*-
"""
Copyright (c) 2019 - present AppSeed.us
"""
import datetime as dt
import json
import re
import socket
import ipaddress
import netifaces
from django.http import HttpResponse, JsonResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import authenticate
from django.contrib.auth.decorators import login_required, user_passes_test
from django.views.decorators.clickjacking import xframe_options_exempt
from django.views.decorators.http import require_http_methods, require_POST
from django.contrib.auth.models import User
from django.contrib import messages
from django.urls import reverse
from django.conf import settings
from rest_framework import generics
from rest_framework.response import Response
from rest_framework.authentication import TokenAuthentication
from rest_framework.authtoken.models import Token
from rest_framework.decorators import (
    api_view,
    permission_classes,
    authentication_classes,
)
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework import status
from django.db import IntegrityError
from django.db.models import Q
from django.views.decorators.csrf import csrf_exempt
import json
from .models import (
    Championship,
    Team,
    Person,
    Round,
    championship_team,
    round_team,
    team_member,
    ChangeLane,
    Session,
    Penalty,
    ChampionshipPenalty,
    RoundPenalty,
    PenaltyQueue,
    Logo,
    Race,
    GridPosition,
    Transponder,
    RaceTransponderAssignment,
    LapCrossing,
    QualifyingKnockoutRule,
)
from .signals import race_end_requested
from .serializers import ChangeLaneSerializer
from .utils import datadecode, is_admin_user
from .forms import DriverForm, TeamForm, JoinChampionshipForm
from django.template import loader
from django.db import models
from django_countries import countries


def current_round():
    end_date = dt.date.today()
    start_date = end_date - dt.timedelta(days=1)
    return Round.objects.filter(
        Q(start__date__range=[start_date, end_date]) & Q(ended__isnull=True)
    ).first()


def active_round():
    start_date = dt.date.today() - dt.timedelta(days=1)
    return Round.objects.filter(
        Q(start__date__gte=start_date) & Q(ended__isnull=True)
    ).first()


def editable_round():
    start_date = dt.date.today() - dt.timedelta(days=1)
    return (
        Round.objects.filter(Q(start__date__gte=start_date), ready=False)
        .order_by("start")
        .first()
    )


def index(request):
    # Page from the theme
    button_matrix = [
        [
            {"label": "Team Carousel", "url": "/teamcarousel-nav/"},
            {"label": "Driver's Queue", "url": "/pending_drivers-nav/"},
            {"label": "Round Info", "url": "/round_info/"},
        ],
        [
            {"label": "Monitor One Team", "url": "/singleteam/"},
            {"label": "All Pit Lanes", "url": "/all_pitlanes/"},
            {"label": "Round Penalties", "url": "/round_penalties/"},
        ],
    ]
    cround = current_round()
    return render(
        request,
        "pages/index.html",
        {
            "round": cround,
            "buttons": button_matrix,
            "organiser_logo": get_organiser_logo(cround),
            "sponsors_logos": get_sponsor_logos(cround),
        },
    )


@xframe_options_exempt
def team_carousel(request):
    cround = current_round()

    # Pre-calculate time limits for all teams to avoid template recalculation
    teams_with_limits = []
    if cround:
        for round_team in cround.round_team_set.all():
            limit_type, limit_value = cround.driver_time_limit(round_team)
            if limit_type and limit_type != "none" and limit_value:
                # Convert timedelta to seconds if needed
                if hasattr(limit_value, "total_seconds"):
                    seconds = limit_value.total_seconds()
                else:
                    seconds = limit_value
                # Attach the time limit to the round_team object for template access
                round_team.time_limit_seconds = seconds
            else:
                round_team.time_limit_seconds = None
            teams_with_limits.append(round_team)

    return render(
        request,
        "pages/teamcarousel.html",
        {
            "round": cround,
            "teams_with_limits": teams_with_limits,
            "organiser_logo": get_organiser_logo(cround),
            "sponsors_logos": get_sponsor_logos(cround),
        },
    )


def team_carousel_with_nav(request):
    """Team carousel view with navigation bar"""
    cround = current_round()

    # Pre-calculate time limits for all teams to avoid template recalculation
    teams_with_limits = []
    if cround:
        for round_team in cround.round_team_set.all():
            limit_type, limit_value = cround.driver_time_limit(round_team)
            if limit_type and limit_type != "none" and limit_value:
                # Convert timedelta to seconds if needed
                if hasattr(limit_value, "total_seconds"):
                    seconds = limit_value.total_seconds()
                else:
                    seconds = limit_value
                # Attach the time limit to the round_team object for template access
                round_team.time_limit_seconds = seconds
            else:
                round_team.time_limit_seconds = None
            teams_with_limits.append(round_team)

    return render(
        request,
        "pages/teamcarousel_nav.html",
        {
            "round": cround,
            "teams_with_limits": teams_with_limits,
            "organiser_logo": get_organiser_logo(cround),
            "sponsors_logos": get_sponsor_logos(cround),
        },
    )


def get_team_card(request):
    cround = current_round()
    team_id = request.GET.get("team_id")
    round_team_instance = get_object_or_404(round_team, pk=team_id)
    assert cround == round_team_instance.round
    is_paused = cround.round_pause_set.filter(end__isnull=True).exists()
    if cround.started:
        elapsed = round(cround.time_elapsed.total_seconds())
        remaining = int(max(0, round(cround.duration.total_seconds() - elapsed)))
    else:
        remaining = round(cround.duration.total_seconds())
        is_paused = True

    context = {
        "round_team": round_team_instance,
        "round": cround,
        "is_paused": is_paused,
        "remaining_seconds": remaining,
    }
    html = render(request, "layout/teamcard.html", context).content.decode("utf-8")
    return JsonResponse({"html": html})


def changelane_info(request, lane_number):
    try:
        cround = current_round()
    except:
        cround = None

    change_lane = None
    if cround:
        try:
            change_lane = ChangeLane.objects.get(round=cround, lane=lane_number)
        except ChangeLane.DoesNotExist:
            pass

    return render(
        request,
        "layout/changelane_info.html",
        {"change_lane": change_lane, "round": cround, "lane_number": lane_number},
    )


def changelane_detail(request, lane_number):
    cround = current_round()
    change_lane = get_object_or_404(ChangeLane, round=cround, lane=lane_number)
    return render(
        request, "layout/changelane_small_detail.html", {"change_lane": change_lane}
    )


def changelane_vdetail(request, lane_number):
    """Large detail view for all_pitlanes"""
    cround = current_round()
    change_lane = get_object_or_404(ChangeLane, round=cround, lane=lane_number)
    return render(
        request, "layout/changelane_vdetail.html", {"change_lane": change_lane}
    )


def update_change_lane(request, lane_number):
    cround = current_round()
    change_lane = get_object_or_404(ChangeLane, round=cround, lane=lane_number)
    if change_lane.open == True:
        change_lane.next_driver()  # This is the function that updates the driver.
    change_lane.save()
    return render(request, "layout/changelane_info.html", {"change_lane": change_lane})


def changedriver_info(request):
    try:
        cround = current_round()
        change_lanes = ChangeLane.objects.filter(round=cround, open=True).order_by(
            "lane"
        )
        return render(
            request, "layout/changedriver_info.html", {"change_lanes": change_lanes}
        )
    except:
        return render(
            request,
            "pages/norace.html",
            {
                "organiser_logo": get_organiser_logo(None),
                "sponsors_logos": get_sponsor_logos(None),
            },
        )


@xframe_options_exempt
def all_pitlanes(request):
    try:
        cround = current_round()
    except:
        cround = None

    if cround:
        change_lanes = ChangeLane.objects.filter(round=cround).order_by("lane")
    else:
        change_lanes = []

    return render(
        request,
        "pages/all_pitlanes.html",
        {"change_lanes": change_lanes, "round": cround},
    )


def is_race_director(user):
    return user.is_authenticated and user.groups.filter(name="Race Director").exists()


def is_admin_or_race_director(user):
    return (
        user.is_authenticated
        and user.groups.filter(name__in=["Admin", "Race Director"]).exists()
    )


@login_required
@user_passes_test(is_race_director)
def racecontrol(request):
    cround = current_round()
    try:
        lanes = cround.change_lanes

        # Get all sessions that are registered but not started or ended
        pending_sessions = (
            Session.objects.filter(
                round=cround,
                register__isnull=False,
                start__isnull=True,
                end__isnull=True,
            )
            .select_related(
                "driver", "driver__team", "driver__member", "driver__team__team"
            )
            .order_by("register")
        )  # Order by registration time

        # For each session, get the team's completed sessions count
        for session in pending_sessions:
            completed_count = Session.objects.filter(
                driver__team=session.driver.team, end__isnull=False
            ).count()

            # Add as property to the session object
            session.team_completed_count = completed_count
        active_race = cround.active_race
        race_sequence = (
            list(cround.races.all()) if not cround.uses_legacy_session_model else []
        )
        return render(
            request,
            "pages/racecontrol.html",
            {
                "round": cround,
                "lanes": lanes,
                "pending_sessions": pending_sessions,
                "settings": {"STOPANDGO_HMAC_SECRET": settings.STOPANDGO_HMAC_SECRET},
                "active_race": active_race,
                "race_sequence": race_sequence,
            },
        )
    except:
        return render(
            request,
            "pages/norace.html",
            {
                "organiser_logo": get_organiser_logo(None),
                "sponsors_logos": get_sponsor_logos(None),
            },
        )


@login_required
@user_passes_test(is_race_director)
def preracecheck(request):
    cround = current_round()
    active_race = cround.active_race

    # Determine eliminated teams for Q2+ races in elimination mode
    excluded_team_ids = set()
    if active_race and active_race.race_type in ("Q2", "Q3"):
        main_race = cround.races.filter(race_type="MAIN").first()
        if main_race:
            excluded_team_ids = set(
                GridPosition.objects.filter(
                    race=main_race, source="KNOCKOUT"
                ).values_list("team_id", flat=True)
            )

    # Phase 1: validate drivers and weights (skip eliminated teams)
    res = cround.pre_race_check(excluded_team_ids=excluded_team_ids or None)
    if res:
        return JsonResponse({"result": False, "error": res})

    # Phase 2: for lap-based rounds, check transponder assignments
    if active_race:
        teams_without_transponder = []
        for rt in cround.round_team_set.filter(retired=False):
            if rt.pk in excluded_team_ids:
                continue
            if not RaceTransponderAssignment.objects.filter(
                race=active_race, team=rt
            ).exists():
                teams_without_transponder.append(
                    f"Team {rt.team.team.name} ({rt.team.number}) has no transponder assigned."
                )

        if teams_without_transponder:
            return JsonResponse({"result": False, "error": teams_without_transponder})

    # Phase 3: all checks passed — activate
    cround.activate_race_ready()
    if active_race and not active_race.ready:
        active_race.ready = True
        active_race.save()

    return JsonResponse({"result": True})


@login_required
@user_passes_test(is_race_director)
def race_start(request):
    cround = current_round()
    active_race = cround.active_race

    if active_race:
        # ---- Lap-based: start the active race ----
        now = dt.datetime.now()

        if active_race.start_mode == "FIRST_CROSSING":
            # Timer stays frozen — Race.started remains None until first passage
            pass
        else:
            # IMMEDIATE: start the race clock now
            active_race.started = now
            active_race.save()

        # Set Round.started on first race start (needed for timing consumer)
        if cround.started is None:
            cround.started = now
            cround.save()

        # Clone transponder assignments from depends_on_race if needed
        if active_race.depends_on_race:
            source = active_race.depends_on_race
            if (
                RaceTransponderAssignment.objects.filter(race=source).exists()
                and not RaceTransponderAssignment.objects.filter(
                    race=active_race
                ).exists()
            ):
                active_race.clone_transponder_assignments_from(source)

        # Start driver sessions — set Session.race on each
        sessions = cround.session_set.filter(
            round=cround,
            register__isnull=False,
            start__isnull=True,
            end__isnull=True,
        )
        for session in sessions:
            session.start = now
            session.race = active_race
            session.save()
    else:
        # ---- Legacy path ----
        cround.start_race()

    return JsonResponse({"result": True})


@login_required
@user_passes_test(is_race_director)
def falsestart(request):
    cround = current_round()
    active_race = cround.active_race

    # Detect armed state: FIRST_CROSSING mode where Round.started is set
    # but Race.started is still None
    is_armed = (
        active_race
        and active_race.started is None
        and active_race.start_mode == "FIRST_CROSSING"
        and cround.started is not None
    )

    if active_race and (active_race.started or is_armed):
        # ---- Lap-based: reset the active race ----
        # Reset sessions for this race
        sessions = cround.session_set.filter(
            round=cround,
            register__isnull=False,
            start__isnull=False,
            end__isnull=True,
        )
        for session in sessions:
            session.start = None
            session.save()

        # Delete any lap crossings recorded while armed/running
        LapCrossing.objects.filter(race=active_race).delete()

        # Delete grid order penalties created during this race
        grid_order_penalty = ChampionshipPenalty.objects.filter(
            championship=cround.championship,
            penalty__name="grid order",
        ).first()
        if grid_order_penalty:
            RoundPenalty.objects.filter(
                round=cround,
                penalty=grid_order_penalty,
            ).delete()

        active_race.started = None
        active_race.save()

        # If this was the first race and Round.started was just set, reset it too
        other_started_races = cround.races.filter(started__isnull=False).exclude(
            pk=active_race.pk
        )
        if not other_started_races.exists() and cround.started is not None:
            cround.started = None
            cround.save()
    else:
        # ---- Legacy path ----
        cround.false_start()

    return JsonResponse({"result": True})


@login_required
@user_passes_test(is_race_director)
def racepaused(request):
    cround = current_round()
    cround.pause_race()
    return JsonResponse({"result": True})


@login_required
@user_passes_test(is_race_director)
def racerestart(request):
    cround = current_round()
    cround.restart_race()
    return JsonResponse({"result": True})


@login_required
@user_passes_test(is_race_director)
def falserestart(request):
    cround = current_round()
    cround.false_restart()
    return JsonResponse({"result": True})


@login_required
@user_passes_test(is_race_director)
def endofrace(request):
    cround = current_round()

    # Determine which race is currently active
    active_race = cround.active_race

    if active_race:
        # ---- Lap-based: end the active race ----
        now = dt.datetime.now()
        active_race.ended = now
        active_race.save()

        # End all active sessions
        sessions = cround.session_set.filter(
            register__isnull=False, start__isnull=False, end__isnull=True
        )
        for session in sessions:
            session.end = now
            session.save()

        # Delete pending (unstarted) sessions
        cround.session_set.filter(
            register__isnull=False, start__isnull=True, end__isnull=True
        ).delete()
        ChangeLane.objects.all().delete()

        # Process qualifying results when a Q-race ends
        if active_race.race_type.startswith("Q"):
            tiebreaker = cround.championship.qualifying_tiebreaker
            main_race = cround.races.filter(race_type="MAIN").first()

            # Elimination mode: assign knockout grid positions
            if active_race.knockout_rules.exists():
                active_race.process_qualifying_knockout()

            # Always: combine all ended Q-races to fill MAIN grid
            if main_race:
                ended_q_races = cround.races.filter(
                    race_type__startswith="Q", ended__isnull=False
                )
                Race.combine_qualifying_results(
                    ended_q_races, main_race, tiebreaker=tiebreaker
                )

        # Check if there is a next race
        next_race = cround.active_race  # re-query after saving
        penalty_count = 0
        if next_race is None:
            # Last race finished — close the round
            cround.ended = now
            cround.save()
            penalty_count = cround.post_race_check()

        return JsonResponse(
            {
                "result": True,
                "penalty_count": penalty_count,
                "has_next_race": next_race is not None,
                "next_race_type": next_race.race_type if next_race else None,
                "next_race_label": next_race.get_race_type_display()
                if next_race
                else None,
            }
        )
    else:
        # ---- Legacy path ----
        race_end_requested.send(sender=endofrace, round_id=cround.id)
        return JsonResponse({"result": True})


@csrf_exempt
@api_view(["POST"])
@permission_classes([AllowAny])
@authentication_classes([])
def agent_login(request):
    """
    API endpoint for user login and token generation.
    """
    cround = current_round()
    if cround is None:
        return Response(
            {"status": "error", "message": "No Championship Round today."},
            status=status.HTTP_401_UNAUTHORIZED,
        )
    # Use external domain from settings instead of internal server details
    # This fixes the issue when Django is behind Nginx proxy
    if hasattr(settings, "APP_HOSTNAME") and settings.APP_HOSTNAME:
        # Check if request is secure (HTTPS) by looking at headers set by reverse proxy
        is_secure = (
            request.META.get("HTTP_X_FORWARDED_PROTO") == "https"
            or request.META.get("HTTP_X_FORWARDED_SSL") == "on"
            or request.is_secure()
        )
        schema = "https" if is_secure else "http"

        # Determine if connection is external by checking if request comes from local network
        def is_external_connection():
            # Get the client IP (accounting for proxy headers)
            client_ip = request.META.get("HTTP_X_REAL_IP") or request.META.get(
                "REMOTE_ADDR"
            )
            if not client_ip:
                return False  # Default to internal if we can't determine IP

            try:
                client_ip_obj = ipaddress.ip_address(client_ip)

                # Get all network interfaces on this server
                for interface in netifaces.interfaces():
                    try:
                        addresses = netifaces.ifaddresses(interface)
                        for addr_family in [netifaces.AF_INET, netifaces.AF_INET6]:
                            if addr_family in addresses:
                                for addr_info in addresses[addr_family]:
                                    if "addr" in addr_info and "netmask" in addr_info:
                                        try:
                                            network = ipaddress.ip_network(
                                                f"{addr_info['addr']}/{addr_info['netmask']}",
                                                strict=False,
                                            )
                                            if client_ip_obj in network:
                                                return False  # Internal - same network
                                        except:
                                            pass
                    except:
                        continue

                # If we get here, client is not on any local network
                return True

            except Exception:
                # If anything fails, default to internal (safer)
                return False

        is_external = is_external_connection()

        if ":" in settings.APP_HOSTNAME:
            # APP_HOSTNAME already includes port
            servurl = f"{schema}://{settings.APP_HOSTNAME}"
        else:
            # Use the port nginx forwarded; omit if it's a standard port for the scheme
            forwarded_port = request.META.get("HTTP_X_FORWARDED_PORT")
            standard_ports = {"http": "80", "https": "443"}
            if forwarded_port and forwarded_port != standard_ports.get(schema):
                servurl = f"{schema}://{settings.APP_HOSTNAME}:{forwarded_port}"
            else:
                servurl = f"{schema}://{settings.APP_HOSTNAME}"
    else:
        # Fallback to original logic if APP_HOSTNAME is not configured
        schema = request.scheme
        server = request.META.get("HTTP_HOST") or request.META.get("SERVER_NAME")
        port = request.META.get("SERVER_PORT")

        if ":" in server:
            # If HTTP_HOST already contains the port (e.g., 'example.com:8000')
            server_name, _ = server.split(":", 1)
        else:
            server_name = server

        if port and port not in ("80", "443"):  # Only include non-standard ports
            servurl = f"{schema}://{server_name}:{port}"
        else:
            servurl = f"{schema}://{server_name}"
    username = request.data.get("username")
    password = request.data.get("password")
    user = authenticate(request, username=username, password=password)
    if user is not None:
        if user.groups.filter(name="Queue Scanner").exists():
            token, created = Token.objects.get_or_create(user=user)
            return Response(
                {"status": "ok", "token": token.key, "url": servurl + "/driver_queue/"},
                status=status.HTTP_200_OK,
            )
        elif user.groups.filter(name="Driver Scanner").exists():
            token, created = Token.objects.get_or_create(user=user)
            return Response(
                {
                    "status": "ok",
                    "token": token.key,
                    "url": servurl + "/driver_change/",
                },
                status=status.HTTP_200_OK,
            )
        else:
            return Response(
                {"status": "error", "message": "This is not your role!"},
                status=status.HTTP_401_UNAUTHORIZED,
            )
    else:
        return Response(
            {"status": "error", "message": "Invalid credentials"},
            status=status.HTTP_401_UNAUTHORIZED,
        )


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def add_driver_to_queue(request):
    """
    API endpoint that requires authentication using a token.
    """
    try:
        cround = current_round()
        payload = json.loads(request.body)  # or request.data if using DRF parsers

        tmpk = datadecode(cround, payload["data"])
        tmember = team_member.objects.get(pk=tmpk)
        # Process the data and perform the desired actions
        try:
            result = cround.driver_register(tmember)
        except Exception as e:
            result = {
                "message": f"Error for {tmember}: {e}",
                "status": "error",
            }
        # print(result)
        return Response(result, status=status.HTTP_200_OK)

    except json.JSONDecodeError:
        return Response(
            {"status": "error", "message": "Invalid JSON data"},
            status=status.HTTP_400_BAD_REQUEST,
        )
    except Exception as e:
        return Response(
            {"status": "error", "message": f"Exception: {e}"},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def change_kart_driver(request):
    """
    API endpoint that requires authentication using a token.
    """
    try:
        cround = current_round()
        payload = json.loads(request.body)  # or request.data if using DRF parsers

        tmpk = datadecode(cround, payload["data"])
        tmember = team_member.objects.get(pk=tmpk)
        # Process the data and perform the desired actions
        try:
            result = cround.driver_endsession(tmember)
        except Exception as e:
            result = {
                "message": f"Error for {tmember}: {e}",
                "status": "error",
            }
        # print(result)
        return Response(result, status=status.HTTP_200_OK)

    except json.JSONDecodeError:
        return Response(
            {"status": "error", "message": "Invalid JSON data"},
            status=status.HTTP_400_BAD_REQUEST,
        )
    except Exception as e:
        return Response(
            {"status": "error", "message": f"Exception: {e}"},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


@login_required
@user_passes_test(is_admin_user)
def round_list_update(request):
    """View to list all not ready rounds for the championship whose next round is the soonest upcoming (today or after)"""
    # Find the next not ready round in any championship
    next_round = editable_round()
    rounds = []
    championship = None
    if next_round:
        championship = next_round.championship
        rounds = Round.objects.filter(championship=championship, ready=False).order_by(
            "start"
        )
    context = {
        "rounds": rounds,
        "next_round": next_round,
        "championship": championship,
        "organiser_logo": get_organiser_logo(next_round),
        "sponsors_logos": get_sponsor_logos(next_round),
    }

    if request.method == "GET" and "round_id" in request.GET:
        try:
            selected_round = Round.objects.get(pk=request.GET["round_id"])
            context["selected_round"] = selected_round
            # Update organiser logo to selected round
            context["organiser_logo"] = get_organiser_logo(selected_round)
            existing_race = selected_round.races.first()
            context["ending_mode_choices"] = Championship.ENDING_MODES
            context["current_ending_mode"] = getattr(
                existing_race, "ending_mode", "CROSS_AFTER_TIME"
            )
            qual_info = _get_qualifying_info(selected_round)
            context["qualifying_count"] = qual_info["qualifying_count"]
            context["qualifying_ending_mode"] = qual_info["qualifying_ending_mode"]
            context["qualifying_grid_method"] = qual_info["qualifying_grid_method"]
            context["qualifying_durations_json"] = json.dumps(
                qual_info["qualifying_durations"]
            )
            context["qualifying_cutoffs_json"] = json.dumps(
                qual_info["qualifying_cutoffs"]
            )
        except Round.DoesNotExist:
            messages.error(request, "Round not found")

    return render(request, "pages/roundedit.html", context)


@login_required
@user_passes_test(is_admin_user)
@require_http_methods(["GET"])
def round_form(request):
    """HTMX view to return the round form partial"""
    round_id = request.GET.get("round_id")

    if not round_id:
        return HttpResponse("Please select a round")

    try:
        cround = Round.objects.get(pk=round_id)

        # Ensure weight_penalty is properly formatted
        if not cround.weight_penalty:
            cround.weight_penalty = [">=", [0, 0]]

        # If it's a string, try to parse it
        if isinstance(cround.weight_penalty, str):
            try:
                cround.weight_penalty = json.loads(cround.weight_penalty)
            except json.JSONDecodeError:
                cround.weight_penalty = [">=", [0, 0]]

        # Convert to JSON string for template
        existing_race = cround.races.first()
        qual_info = _get_qualifying_info(cround)
        context = {
            "round": cround,
            "ending_mode_choices": Championship.ENDING_MODES,
            "current_ending_mode": getattr(
                existing_race, "ending_mode", "CROSS_AFTER_TIME"
            ),
            "qualifying_count": qual_info["qualifying_count"],
            "qualifying_ending_mode": qual_info["qualifying_ending_mode"],
            "qualifying_grid_method": qual_info["qualifying_grid_method"],
            "qualifying_durations_json": json.dumps(qual_info["qualifying_durations"]),
            "qualifying_cutoffs_json": json.dumps(qual_info["qualifying_cutoffs"]),
        }
        return render(request, "layout/roundedit.html", context)
    except Round.DoesNotExist:
        return HttpResponse("Round not found")


def _get_qualifying_info(round_obj):
    """Extract qualifying configuration from existing races for a round."""
    races = round_obj.races.all().order_by("sequence_number")
    q_races = [r for r in races if r.race_type in ("Q1", "Q2", "Q3")]
    qualifying_count = len(q_races)

    def fmt_dur(td):
        if not td:
            return "00:15:00"
        total = int(td.total_seconds())
        h, rem = divmod(total, 3600)
        m, s = divmod(rem, 60)
        return f"{h:02d}:{m:02d}:{s:02d}"

    durations = {}
    for r in q_races:
        idx = int(r.race_type[1])  # Q1->1, Q2->2, Q3->3
        durations[f"q{idx}"] = fmt_dur(r.time_limit_override)

    # Determine grid method from knockout rules
    qualifying_grid_method = "best_time"
    cutoffs = {}
    if q_races:
        rules = QualifyingKnockoutRule.objects.filter(
            qualifying_race__in=q_races
        ).order_by("qualifying_race__sequence_number")
        if rules.exists():
            qualifying_grid_method = "elimination"
            for rule in rules:
                idx = int(rule.qualifying_race.race_type[1])
                cutoffs[f"q{idx}"] = rule.eliminates_to_position_range_start

    return {
        "qualifying_count": qualifying_count,
        "qualifying_ending_mode": q_races[0].ending_mode if q_races else "QUALIFYING",
        "qualifying_grid_method": qualifying_grid_method,
        "qualifying_durations": durations,
        "qualifying_cutoffs": cutoffs,
    }


def _parse_duration(duration_str):
    """Parse a duration string (HH:MM:SS or MM:SS) into a timedelta."""
    if not duration_str:
        return dt.timedelta(0)
    if ":" in duration_str:
        parts = duration_str.split(":")
        if len(parts) == 3:
            hours, minutes, seconds = map(int, parts)
            return dt.timedelta(hours=hours, minutes=minutes, seconds=seconds)
        elif len(parts) == 2:
            minutes, seconds = map(int, parts)
            return dt.timedelta(minutes=minutes, seconds=seconds)
    try:
        minutes = float(duration_str)
        return dt.timedelta(minutes=minutes)
    except ValueError:
        pass
    return dt.timedelta(0)


def _create_qualifying_races(cround, post_data, ending_mode):
    """
    Create qualifying and main race objects from form data.
    Deletes existing races (if none started) and recreates.
    """
    # Guard: don't delete if a race has started
    if Race.objects.filter(round=cround, started__isnull=False).exists():
        return False, "Cannot reconfigure: a race has already started."

    # Clean up existing races and knockout rules
    QualifyingKnockoutRule.objects.filter(qualifying_race__round=cround).delete()
    Race.objects.filter(round=cround).delete()

    qualifying_count = int(post_data.get("qualifying_count", 0))
    qualifying_ending_mode = post_data.get("qualifying_ending_mode", "QUALIFYING")
    qualifying_grid_method = post_data.get("qualifying_grid_method", "best_time")

    seq = 1
    q_races = []
    prev_race = None

    for i in range(1, qualifying_count + 1):
        q_duration = _parse_duration(post_data.get(f"q{i}_duration", "00:15:00"))
        race_type = f"Q{i}"
        q_race = Race.objects.create(
            round=cround,
            race_type=race_type,
            sequence_number=seq,
            ending_mode=qualifying_ending_mode,
            time_limit_override=q_duration,
            depends_on_race=prev_race,
        )
        q_races.append(q_race)
        prev_race = q_race
        seq += 1

    # Create MAIN race
    main_race = Race.objects.create(
        round=cround,
        race_type="MAIN",
        sequence_number=seq,
        ending_mode=ending_mode,
        time_limit_override=cround.duration,
        depends_on_race=prev_race,
    )

    # Create knockout rules for elimination mode
    if qualifying_grid_method == "elimination" and qualifying_count > 1:
        for i in range(qualifying_count - 1):
            cutoff = post_data.get(f"q{i+1}_cutoff")
            if cutoff:
                cutoff = int(cutoff)
                # Teams from position cutoff+1 to end are eliminated
                QualifyingKnockoutRule.objects.create(
                    qualifying_race=q_races[i],
                    eliminates_to_position_range_start=cutoff,
                    eliminates_to_position_range_end=-1,
                    sets_grid_positions_for=main_race,
                    grid_position_offset=cutoff,
                )

    return True, None


@login_required
@user_passes_test(is_admin_user)
@require_http_methods(["POST"])
def update_round(request, round_id):
    """Handle the form submission to update a round"""
    cround = get_object_or_404(Round, pk=round_id)
    if cround.ready:
        messages.error(request, "This round can no longer be modified.")
    else:
        try:
            # Update basic fields
            cround.name = request.POST.get("name")
            cround.start = request.POST.get("start")

            # Parse duration strings
            def parse_duration(duration_str):
                if ":" in duration_str:
                    parts = duration_str.split(":")
                    if len(parts) == 3:  # HH:MM:SS
                        hours, minutes, seconds = map(int, parts)
                        return dt.timedelta(
                            hours=hours, minutes=minutes, seconds=seconds
                        )
                    elif len(parts) == 2:  # MM:SS
                        minutes, seconds = map(int, parts)
                        return dt.timedelta(minutes=minutes, seconds=seconds)
                # Try to parse as minutes
                try:
                    minutes = float(duration_str)
                    return dt.timedelta(minutes=minutes)
                except ValueError:
                    pass
                return dt.timedelta(0)  # Default

            cround.duration = parse_duration(request.POST.get("duration"))
            cround.pitlane_open_after = parse_duration(
                request.POST.get("pitlane_open_after")
            )
            cround.pitlane_close_before = parse_duration(
                request.POST.get("pitlane_close_before")
            )
            cround.limit_time_min = parse_duration(request.POST.get("limit_time_min"))

            # Update other fields
            cround.change_lanes = int(request.POST.get("change_lanes"))
            cround.limit_time = request.POST.get("limit_time")
            cround.limit_method = request.POST.get("limit_method")
            cround.limit_value = int(request.POST.get("limit_value"))
            cround.required_changes = int(request.POST.get("required_changes"))

            # Handle weight_penalty JSON field
            weight_penalty_json = request.POST.get("weight_penalty", '[">=", [0, 0]]')
            try:
                weight_penalty = json.loads(weight_penalty_json)
                cround.weight_penalty = weight_penalty
            except json.JSONDecodeError:
                messages.error(request, "Invalid weight penalty format")
                return redirect("rounds_list")

            # Handle lap-based timing toggle
            lap_based = request.POST.get("lap_based") == "on"
            was_legacy = cround.uses_legacy_session_model

            if lap_based:
                cround.uses_legacy_session_model = False
                cround.save()
                ending_mode = request.POST.get("ending_mode", "CROSS_AFTER_TIME")
                ok, err = _create_qualifying_races(cround, request.POST, ending_mode)
                if not ok:
                    messages.error(request, err)
                    return redirect("rounds_list")
            elif not lap_based and not was_legacy:
                # Disabling lap-based: clean up Race objects
                if Race.objects.filter(round=cround, started__isnull=False).exists():
                    messages.error(
                        request,
                        "Cannot disable transponder timing: a race has already started.",
                    )
                    return redirect("rounds_list")
                QualifyingKnockoutRule.objects.filter(
                    qualifying_race__round=cround
                ).delete()
                Race.objects.filter(round=cround).delete()
                cround.uses_legacy_session_model = True
                cround.save()
            else:
                cround.save()

            messages.success(request, f"Round '{cround.name}' updated successfully")

        except Exception as e:
            messages.error(request, f"Error updating round: {str(e)}")

    return redirect("rounds_list")


@login_required
@user_passes_test(is_admin_user)
def create_driver(request):
    if request.method == "POST":
        form = DriverForm(request.POST, request.FILES)
        if form.is_valid():
            form.save()
            messages.success(request, "Driver added successfully!")
            return redirect("add_driver")  # Redirect to a page listing persons
    else:
        form = DriverForm()
    return render(
        request,
        "pages/add_driver.html",
        {
            "form": form,
            "organiser_logo": get_organiser_logo(current_round()),
            "sponsors_logos": get_sponsor_logos(current_round()),
        },
    )


@login_required
@user_passes_test(is_admin_user)
def create_team(request):
    if request.method == "POST":
        form = TeamForm(request.POST, request.FILES)
        if form.is_valid():
            team = form.save()

            championship = form.cleaned_data.get("championship")
            team_number = form.cleaned_data.get("team_number")

            if championship and team_number:
                try:
                    championship_team.objects.create(
                        championship=championship, team=team, number=team_number
                    )
                except IntegrityError:
                    # Handle the rare case where someone else took the number
                    # between form validation and saving
                    form.add_error(
                        "team_number", "This team number is no longer available."
                    )
                    team.delete()  # Clean up the team if registration failed
                    return render(
                        request,
                        "pages/add_team.html",
                        {
                            "form": form,
                            "organiser_logo": get_organiser_logo(current_round()),
                            "sponsors_logos": get_sponsor_logos(current_round()),
                        },
                    )
            messages.success(request, "Team added successfully!")
            return redirect("add_team")  # Redirect to a page listing persons
    else:
        form = TeamForm()
    return render(
        request,
        "pages/add_team.html",
        {"form": form, "organiser_logo": get_organiser_logo(current_round())},
    )


def get_round_status(request):
    """Return the current round status as JSON"""
    # Get the current active round (you can use your existing method)
    cround = current_round()

    if not cround:
        return JsonResponse({"ready": False, "ongoing": False, "is_paused": True})

    return JsonResponse(
        {
            "ready": cround.ready,
            "ongoing": cround.ongoing,
            "is_paused": cround.is_paused,
        }
    )


def get_race_lanes(request):
    """Return the lanes for the current race"""
    # Get the current active round (use your existing method)
    cround = current_round()

    if not cround:
        return JsonResponse({"lanes": []})

    # Get lanes for this round
    lanes = ChangeLane.objects.filter(round=cround).values("id", "lane")

    return JsonResponse({"lanes": list(lanes)})


def driver_session_timer(request, driver_id):
    """Return the HTML for a driver's session timer"""
    driver = get_object_or_404(team_member, id=driver_id)

    # Load the timer template tag
    template = loader.get_template("layout/session_timer_snippet.html")
    context = {"member": driver}
    return HttpResponse(template.render(context, request))


def singleteam_view(request):
    """
    View to display a single team selected from a dropdown
    """
    try:
        cround = current_round()
    except:
        cround = None

    if cround:
        # Always get all teams for the dropdown
        teams = cround.round_team_set.all().order_by("team__number")

        # Handle team selection from POST
        selected_team = None
        if request.method == "POST":
            selected_team_id = request.POST.get("team_id")
            if selected_team_id and selected_team_id.isdigit():
                try:
                    # Get just the specific round_team by ID
                    selected_team = cround.round_team_set.get(id=selected_team_id)
                except round_team.DoesNotExist:
                    selected_team = None
        # For initial page load, optionally default to first team
        elif teams.exists():
            selected_team = teams.first()

        # Pre-calculate time limit for selected team to avoid template recalculation
        if selected_team:
            limit_type, limit_value = cround.driver_time_limit(selected_team)
            if limit_type and limit_type != "none" and limit_value:
                # Convert timedelta to seconds if needed
                if hasattr(limit_value, "total_seconds"):
                    seconds = limit_value.total_seconds()
                else:
                    seconds = limit_value
                # Attach the time limit to the round_team object for template access
                selected_team.time_limit_seconds = seconds
            else:
                selected_team.time_limit_seconds = None

        context = {
            "round": cround,
            "teams": teams,
            "selected_team": selected_team,
            "organiser_logo": get_organiser_logo(cround),
            "sponsors_logos": get_sponsor_logos(cround),
        }
        return render(request, "pages/singleteam.html", context)
    else:
        return render(
            request,
            "pages/norace.html",
            {
                "organiser_logo": get_organiser_logo(None),
                "sponsors_logos": get_sponsor_logos(None),
            },
        )


@xframe_options_exempt
def pending_drivers(request):
    """View to display all pending sessions for the current round"""
    try:
        cround = current_round()
    except:
        cround = None

    # If no round is found
    if not cround:
        return render(
            request,
            "pages/pending_drivers.html",
            {
                "round": None,
                "organiser_logo": None,
                "sponsors_logos": get_sponsor_logos(None),
            },
        )

    # Get all sessions that are registered but not started or ended
    pending_sessions = (
        Session.objects.filter(
            round=cround,
            register__isnull=False,
            start__isnull=True,
            end__isnull=True,
        )
        .select_related(
            "driver", "driver__team", "driver__member", "driver__team__team"
        )
        .order_by("register")
    )  # Order by registration time

    # For each session, get the team's completed sessions count
    for session in pending_sessions:
        completed_count = Session.objects.filter(
            driver__team=session.driver.team, end__isnull=False
        ).count()

        # Add as property to the session object
        session.team_completed_count = completed_count

    context = {
        "round": cround,
        "pending_sessions": pending_sessions,
        "organiser_logo": get_organiser_logo(cround),
    }

    return render(request, "pages/pending_drivers.html", context)


def pending_drivers_with_nav(request):
    """View to display all pending sessions for the current round with navigation"""
    try:
        cround = current_round()
    except:
        cround = None

    # If no round is found
    if not cround:
        return render(
            request,
            "pages/pending_drivers_nav.html",
            {
                "round": None,
                "organiser_logo": None,
                "sponsors_logos": get_sponsor_logos(None),
            },
        )

    # Get all sessions that are registered but not started or ended
    pending_sessions = (
        Session.objects.filter(
            round=cround,
            register__isnull=False,
            start__isnull=True,
            end__isnull=True,
        )
        .select_related(
            "driver", "driver__team", "driver__member", "driver__team__team"
        )
        .order_by("register")
    )  # Order by registration time

    # For each session, get the team's completed sessions count
    for session in pending_sessions:
        completed_count = Session.objects.filter(
            driver__team=session.driver.team, end__isnull=False
        ).count()

        # Add as property to the session object
        session.team_completed_count = completed_count

    context = {
        "round": cround,
        "pending_sessions": pending_sessions,
        "organiser_logo": get_organiser_logo(cround),
        "sponsors_logos": get_sponsor_logos(cround),
    }

    return render(request, "pages/pending_drivers_nav.html", context)


def driver_info_api(request, driver_id):
    """API endpoint to get driver info for the pending sessions table"""
    driver = get_object_or_404(team_member, pk=driver_id)

    # Return the needed information for the front-end
    return JsonResponse(
        {
            "driver_id": driver.id,
            "team_id": driver.team.id,
            "team_number": driver.team.number,
            "nickname": driver.member.nickname,
        }
    )


@login_required
@user_passes_test(is_admin_user)
def join_championship_view(request):
    if request.method == "POST":
        form = JoinChampionshipForm(request.POST)
        if form.is_valid():
            championship = form.cleaned_data["championship"]
            team_id = form.cleaned_data["team"]
            number = form.cleaned_data["number"]

            try:
                team = Team.objects.get(id=team_id)
                championship_team.objects.create(
                    championship=championship, team=team, number=number
                )
                # Store success message in session
                request.session[
                    "success_message"
                ] = f"Successfully added {team.name} to {championship.name} with number {number}!"
                return redirect("join_championship")
            except Team.DoesNotExist:
                form.add_error("team", "Selected team does not exist.")
            except IntegrityError:
                form.add_error(
                    None, "This team or number is already taken in this championship."
                )
    else:
        form = JoinChampionshipForm()

        # Get and clear success message from session
        success_message = request.session.pop("success_message", None)

    return render(
        request,
        "pages/join_championship.html",
        {
            "form": form,
            "success_message": success_message,
            "organiser_logo": get_organiser_logo(current_round()),
            "sponsors_logos": get_sponsor_logos(current_round()),
        },
    )


@login_required
@user_passes_test(is_admin_user)
@require_POST
def get_available_teams(request):
    print(f"Available teams with {request}")
    championship_id = request.POST.get("championship_id")
    if not championship_id:
        return JsonResponse({"teams": []})

    joined_teams = championship_team.objects.filter(
        championship_id=championship_id
    ).values_list("team_id", flat=True)

    available_teams = Team.objects.exclude(id__in=joined_teams).values("id", "name")

    return JsonResponse({"teams": list(available_teams)})


@login_required
@user_passes_test(is_admin_user)
@require_POST
def get_available_numbers(request):
    print(f"Available number with {request}")
    championship_id = request.POST.get("championship_id")
    if not championship_id:
        return JsonResponse({"numbers": []})

    used_numbers = championship_team.objects.filter(
        championship_id=championship_id
    ).values_list("number", flat=True)

    available_numbers = [str(i) for i in range(1, 100) if i not in used_numbers]

    return JsonResponse({"numbers": available_numbers})


def round_info(request):
    # Get all rounds sorted by date
    rounds = Round.objects.select_related("championship").all().order_by("start")

    # Group rounds by championship name
    rounds_by_championship = {}
    for round_obj in rounds:
        championship_name = round_obj.championship.name
        if championship_name not in rounds_by_championship:
            rounds_by_championship[championship_name] = []
        rounds_by_championship[championship_name].append(round_obj)

    # Find closest round to today
    selected_round_id = request.GET.get("round_id")
    if not selected_round_id:
        today = dt.date.today()
        closest_round = rounds.filter(start__date__gte=today).first()
        if not closest_round:
            closest_round = rounds.last()
        selected_round_id = closest_round.id if closest_round else None

    selected_round = None
    round_teams = []

    if selected_round_id:
        selected_round = Round.objects.get(id=selected_round_id)
        round_teams = round_team.objects.filter(round=selected_round)

        # For each team, preload related members and their sessions
        for rt in round_teams:
            # Get the completed sessions count
            rt.completed_sessions_count = Session.objects.filter(
                round=selected_round, driver__team=rt, end__isnull=False
            ).count()

            # Get all team members
            rt.members = team_member.objects.filter(team=rt)

            # For each member, preload their sessions
            for member in rt.members:
                member.sessions_count = Session.objects.filter(
                    driver=member, end__isnull=False
                ).count()

                member.all_sessions = Session.objects.filter(driver=member).order_by(
                    "start"
                )

    context = {
        "rounds": rounds,
        "rounds_by_championship": rounds_by_championship,
        "selected_round": selected_round,
        "selected_round_id": int(selected_round_id) if selected_round_id else None,
        "round_teams": round_teams,
        "organiser_logo": get_organiser_logo(selected_round),
        "sponsors_logos": get_sponsor_logos(selected_round),
    }
    return render(request, "pages/round_info.html", context)


def round_penalties(request):
    """View to display penalties for a selected round with dropdown similar to round_info."""
    # Get all rounds sorted by date
    rounds = Round.objects.select_related("championship").all().order_by("start")

    # Group rounds by championship name
    rounds_by_championship = {}
    for round_obj in rounds:
        championship_name = round_obj.championship.name
        if championship_name not in rounds_by_championship:
            rounds_by_championship[championship_name] = []
        rounds_by_championship[championship_name].append(round_obj)

    # Find closest round to today
    selected_round_id = request.GET.get("round_id")
    if not selected_round_id:
        today = dt.date.today()
        closest_round = rounds.filter(start__date__gte=today).first()
        if not closest_round:
            closest_round = rounds.last()
        selected_round_id = closest_round.id if closest_round else None

    selected_round = None
    round_penalties_list = []

    if selected_round_id:
        selected_round = Round.objects.get(id=selected_round_id)

        # Get all penalties for this round with related data
        round_penalties_list = (
            RoundPenalty.objects.filter(round=selected_round)
            .select_related(
                "penalty__penalty",
                "offender__team__team",
                "victim__team__team",
            )
            .order_by("imposed")
        )

        # Add formatted penalty text for each penalty
        for penalty in round_penalties_list:
            if penalty.penalty.sanction in ["S", "D"]:  # Stop & Go and Self Stop & Go
                penalty.penalty_text = f"Stop & Go {penalty.value} seconds"
            elif penalty.penalty.sanction in ["L", "P"]:  # Laps and Post Race Laps
                penalty.penalty_text = f"{penalty.value} laps"
            else:
                penalty.penalty_text = f"{penalty.penalty.penalty.name} {penalty.value}"

    context = {
        "rounds": rounds,
        "rounds_by_championship": rounds_by_championship,
        "selected_round": selected_round,
        "selected_round_id": int(selected_round_id) if selected_round_id else None,
        "round_penalties": round_penalties_list,
        "organiser_logo": get_organiser_logo(selected_round),
        "sponsors_logos": get_sponsor_logos(selected_round),
    }
    return render(request, "pages/round_penalties.html", context)


def all_drivers_view(request):
    # Get all championships with end date after today
    today = dt.date.today()
    championships = Championship.objects.filter(end__gte=today).order_by("-end")

    selected_championship_id = request.GET.get("championship")
    selected_championship = None
    rounds = []
    persons = []

    if selected_championship_id:
        selected_championship = get_object_or_404(
            Championship, id=selected_championship_id
        )
        rounds = Round.objects.filter(championship=selected_championship).order_by(
            "start"
        )

        # Get all persons who are team members in any round of this championship
        persons = Person.objects.filter(
            team_member__team__round__championship=selected_championship
        ).distinct()

        # For each person, get their team information for each round
        for person in persons:
            person.teams = []
            for round_obj in rounds:
                team_members = team_member.objects.filter(
                    team__round=round_obj, member=person
                ).select_related("team__team")

                for tm in team_members:
                    person.teams.append(
                        {
                            "round_id": round_obj.id,
                            "number": tm.team.number,
                            "name": tm.team.name,
                        }
                    )

    # Get organiser logo for current round or selected championship
    current_round_obj = current_round()
    if selected_championship and not current_round_obj:
        # If no current round but we have a selected championship, use latest round from that championship
        latest_round = rounds.last() if rounds else None
        organiser_logo = get_organiser_logo(latest_round)
        sponsors_logos = get_sponsor_logos(latest_round)
    else:
        organiser_logo = get_organiser_logo(current_round_obj)
        sponsors_logos = get_sponsor_logos(current_round_obj)

    context = {
        "championships": championships,
        "selected_championship": selected_championship,
        "rounds": rounds,
        "persons": persons,
        "organiser_logo": organiser_logo,
        "sponsors_logos": sponsors_logos,
    }

    return render(request, "pages/alldriver.html", context)


def all_teams_view(request):
    # Get all championships that haven't ended yet
    championships = Championship.objects.filter(end__gte=dt.date.today()).order_by(
        "-end"
    )

    selected_championship = None
    rounds = []
    teams = []

    championship_id = request.GET.get("championship")
    if championship_id:
        selected_championship = get_object_or_404(Championship, id=championship_id)
        rounds = Round.objects.filter(championship=selected_championship).order_by(
            "start"
        )

        # Get all teams and their round participation
        teams = (
            Team.objects.annotate(
                championship_number=models.Case(
                    models.When(
                        championship_team__championship=selected_championship,
                        then=models.F("championship_team__number"),
                    ),
                    default=models.Value(
                        999
                    ),  # Teams without a number will be sorted last
                    output_field=models.IntegerField(),
                )
            )
            .prefetch_related(
                "championship_team_set",
                "championship_team_set__round_team_set",
                "championship_team_set__round_team_set__round",
            )
            .order_by("championship_number")
        )

    # Get organiser logo for current round or selected championship
    current_round_obj = current_round()
    if selected_championship and not current_round_obj:
        # If no current round but we have a selected championship, use latest round from that championship
        latest_round = rounds.last() if rounds else None
        organiser_logo = get_organiser_logo(latest_round)
        sponsors_logos = get_sponsor_logos(latest_round)
    else:
        organiser_logo = get_organiser_logo(current_round_obj)
        sponsors_logos = get_sponsor_logos(current_round_obj)

    context = {
        "championships": championships,
        "selected_championship": selected_championship,
        "rounds": rounds,
        "teams": teams,
        "organiser_logo": organiser_logo,
        "sponsors_logos": sponsors_logos,
    }

    return render(request, "pages/allteams.html", context)


@login_required
@user_passes_test(is_admin_user)
def edit_driver_view(request):
    if request.method == "POST":
        try:
            driver_id = request.POST.get("driver_id")
            driver = get_object_or_404(Person, id=driver_id)

            # Update driver fields
            driver.surname = request.POST.get("surname")
            driver.firstname = request.POST.get("firstname")
            driver.nickname = request.POST.get("nickname")
            driver.gender = request.POST.get("gender")
            driver.birthdate = request.POST.get("birthdate")
            driver.country = request.POST.get("country")
            driver.email = request.POST.get("email") or None

            # Handle mugshot upload
            if "mugshot" in request.FILES:
                driver.mugshot = request.FILES["mugshot"]

            driver.save()
            return JsonResponse({"success": True})
        except Exception as e:
            return JsonResponse({"success": False, "error": str(e)})

    # GET request - show the form
    drivers = Person.objects.all().order_by("nickname")
    countries_list = list(countries)

    context = {
        "drivers": drivers,
        "countries": countries_list,
        "organiser_logo": get_organiser_logo(current_round()),
        "sponsors_logos": get_sponsor_logos(current_round()),
    }
    return render(request, "pages/edit_driver.html", context)


@login_required
@user_passes_test(is_admin_user)
def edit_team_view(request):
    if request.method == "POST":
        try:
            team_id = request.POST.get("team_id")
            team = get_object_or_404(Team, id=team_id)

            # Update team fields
            team.name = request.POST.get("name")

            # Handle logo upload
            if "logo" in request.FILES:
                team.logo = request.FILES["logo"]

            team.save()
            return JsonResponse({"success": True})
        except Exception as e:
            return JsonResponse({"success": False, "error": str(e)})

    # GET request - show the form
    teams = Team.objects.all().order_by("name")

    context = {
        "teams": teams,
        "organiser_logo": get_organiser_logo(current_round()),
        "sponsors_logos": get_sponsor_logos(current_round()),
    }
    return render(request, "pages/edit_team.html", context)


@login_required
@user_passes_test(is_admin_user)
def create_championship_view(request):
    if request.method == "POST":
        try:
            name = request.POST.get("name")
            year = int(request.POST.get("year"))
            num_rounds = int(request.POST.get("rounds"))

            # Create championship with start and end dates
            start_date = dt.date(year, 1, 1)
            end_date = dt.date(year, 12, 31)

            championship = Championship.objects.create(
                name=name, start=start_date, end=end_date
            )

            # Create rounds
            # Calculate days between rounds to spread them evenly
            days_between_rounds = (end_date - start_date).days // (num_rounds + 1)
            current_date = start_date + dt.timedelta(days=days_between_rounds)

            for i in range(num_rounds):
                round_start = dt.datetime.combine(current_date, dt.time(18, 0))  # 18:00
                Round.objects.create(
                    championship=championship,
                    name=f"Round {i + 1}",
                    start=round_start,
                    duration=dt.timedelta(hours=4),
                    ready=False,
                )
                current_date += dt.timedelta(days=days_between_rounds)

            return JsonResponse({"success": True})
        except Exception as e:
            return JsonResponse({"success": False, "error": str(e)})

    # GET request - show the form
    current_year = dt.date.today().year
    context = {
        "current_year": current_year,
        "organiser_logo": get_organiser_logo(current_round()),
        "sponsors_logos": get_sponsor_logos(current_round()),
    }
    return render(request, "pages/create_championship.html", context)


@login_required
@user_passes_test(is_admin_user)
def edit_championship_view(request):
    if request.method == "POST":
        try:
            action = request.POST.get("action")

            # Handle penalty actions that don't need championship object
            if action == "delete_championship_penalty":
                # Delete championship penalty
                championship_penalty_id = request.POST.get("championship_penalty_id")
                championship_penalty = get_object_or_404(
                    ChampionshipPenalty, id=championship_penalty_id
                )
                championship_penalty.delete()

                return JsonResponse(
                    {
                        "success": True,
                        "message": "Championship penalty deleted successfully",
                    }
                )

            elif action == "edit_championship_penalty":
                # Edit championship penalty
                championship_penalty_id = request.POST.get("championship_penalty_id")
                sanction = request.POST.get("sanction")
                value = request.POST.get("value")
                option = request.POST.get("option", "fixed")

                championship_penalty = get_object_or_404(
                    ChampionshipPenalty, id=championship_penalty_id
                )
                championship_penalty.sanction = sanction
                championship_penalty.value = int(value)
                championship_penalty.option = option
                championship_penalty.save()

                return JsonResponse(
                    {
                        "success": True,
                        "message": "Championship penalty updated successfully",
                    }
                )

            # For other actions, get the championship
            championship_id = request.POST.get("championship_id")
            championship = get_object_or_404(Championship, id=championship_id)

            # Only update championship fields if this is not a round management action
            if not action:
                # Update championship fields
                championship.name = request.POST.get("name")
                year_str = request.POST.get("year")
                if year_str:
                    year = int(year_str)
                    # Update start and end dates
                    championship.start = dt.date(year, 1, 1)
                    championship.end = dt.date(year, 12, 31)

                championship.save()

            if action == "add_round":
                # Add a new round
                round_num_re = re.compile(r"Round (\d+)")
                all_rounds = list(
                    Round.objects.filter(championship=championship).order_by("start")
                )
                max_round_num = 0
                for rnd in all_rounds:
                    m = round_num_re.match(rnd.name)
                    if m:
                        n = int(m.group(1))
                        if n > max_round_num:
                            max_round_num = n
                next_round_num = max_round_num + 1
                existing_rounds = Round.objects.filter(
                    championship=championship
                ).order_by("start")
                if existing_rounds.exists():
                    last_round = existing_rounds.last()
                    new_start = last_round.start + dt.timedelta(
                        days=7
                    )  # 1 week after last round
                else:
                    # First round - start 1 week after championship start
                    new_start = dt.datetime.combine(
                        championship.start + dt.timedelta(days=7), dt.time(18, 0)
                    )
                Round.objects.create(
                    championship=championship,
                    name=f"Round {next_round_num}",
                    start=new_start,
                    duration=dt.timedelta(hours=4),
                    ready=False,
                )

            elif action == "delete_round":
                # Delete the latest round (ready=False only)
                latest_round = (
                    Round.objects.filter(championship=championship, ready=False)
                    .order_by("-start")
                    .first()
                )
                if latest_round:
                    latest_round.delete()

            elif action == "add_championship_penalty":
                # Add championship penalty
                championship_id = request.POST.get("championship_id")
                penalty_id = request.POST.get("penalty_id")
                sanction = request.POST.get("sanction")
                value = request.POST.get("value")
                option = request.POST.get("option", "fixed")

                championship = get_object_or_404(Championship, id=championship_id)
                penalty = get_object_or_404(Penalty, id=penalty_id)

                # Check if this penalty is already configured for this championship
                if ChampionshipPenalty.objects.filter(
                    championship=championship, penalty=penalty
                ).exists():
                    return JsonResponse(
                        {
                            "success": False,
                            "error": "This penalty is already configured for this championship.",
                        }
                    )

                ChampionshipPenalty.objects.create(
                    championship=championship,
                    penalty=penalty,
                    sanction=sanction,
                    value=int(value),
                    option=option,
                )

                return JsonResponse(
                    {
                        "success": True,
                        "message": "Championship penalty added successfully",
                    }
                )

            elif action == "set_rounds":
                # Set specific number of rounds
                num_rounds_str = request.POST.get("num_rounds", "0")
                target_rounds = int(num_rounds_str) if num_rounds_str else 0
                ready_true_rounds = list(
                    Round.objects.filter(
                        championship=championship, ready=True
                    ).order_by("start")
                )
                ready_false_rounds = list(
                    Round.objects.filter(
                        championship=championship, ready=False
                    ).order_by("start")
                )
                ready_true_count = len(ready_true_rounds)
                ready_false_count = len(ready_false_rounds)

                if target_rounds < ready_true_count:
                    return JsonResponse(
                        {
                            "success": False,
                            "error": f"Cannot set number of rounds less than the number of started/completed rounds ({ready_true_count}).",
                        }
                    )

                desired_ready_false = target_rounds - ready_true_count
                current_ready_false = ready_false_count

                # Find the highest round number among all rounds (ready or not)
                round_num_re = re.compile(r"Round (\d+)")
                all_rounds = list(
                    Round.objects.filter(championship=championship).order_by("start")
                )
                max_round_num = 0
                for rnd in all_rounds:
                    m = round_num_re.match(rnd.name)
                    if m:
                        n = int(m.group(1))
                        if n > max_round_num:
                            max_round_num = n
                next_round_num = max_round_num + 1

                if desired_ready_false == 0:
                    # Delete all ready=False rounds
                    Round.objects.filter(
                        championship=championship, ready=False
                    ).delete()
                elif desired_ready_false > current_ready_false:
                    # Add rounds
                    existing_rounds = Round.objects.filter(
                        championship=championship
                    ).order_by("start")
                    if existing_rounds.exists():
                        last_round = existing_rounds.last()
                        base_start = last_round.start
                    else:
                        base_start = dt.datetime.combine(
                            championship.start + dt.timedelta(days=7), dt.time(18, 0)
                        )
                    for i in range(desired_ready_false - current_ready_false):
                        new_start = base_start + dt.timedelta(days=7 * (i + 1))
                        Round.objects.create(
                            championship=championship,
                            name=f"Round {next_round_num + i}",
                            start=new_start,
                            duration=dt.timedelta(hours=4),
                            ready=False,
                        )
                elif desired_ready_false < current_ready_false:
                    # Delete rounds (always delete the latest ones, only ready=False)
                    rounds_to_delete = current_ready_false - desired_ready_false
                    latest_rounds = Round.objects.filter(
                        championship=championship, ready=False
                    ).order_by("-start")[:rounds_to_delete]
                    for round_obj in latest_rounds:
                        round_obj.delete()
                    # After deletion, re-number remaining ready=False rounds
                    # Find the highest round number among all rounds again
                    all_rounds = list(
                        Round.objects.filter(championship=championship).order_by(
                            "start"
                        )
                    )
                    max_round_num = 0
                    for rnd in all_rounds:
                        m = round_num_re.match(rnd.name)
                        if m:
                            n = int(m.group(1))
                            if n > max_round_num:
                                max_round_num = n
                    next_round_num = max_round_num + 1
                    remaining_false = list(
                        Round.objects.filter(
                            championship=championship, ready=False
                        ).order_by("start")
                    )
                    for idx, rnd in enumerate(remaining_false):
                        rnd.name = f"Round {next_round_num + idx}"
                        rnd.save()

            return JsonResponse({"success": True})
        except Exception as e:
            return JsonResponse({"success": False, "error": str(e)})

    # GET request - show the form
    championships = Championship.objects.all().order_by("-start")

    context = {
        "championships": championships,
        "sanction_choices": ChampionshipPenalty.PTYPE,
        "option_choices": ChampionshipPenalty.OPTION_CHOICES,
        "organiser_logo": get_organiser_logo(current_round()),
        "sponsors_logos": get_sponsor_logos(current_round()),
    }
    return render(request, "pages/edit_championship.html", context)


@login_required
@user_passes_test(is_admin_user)
def edit_round_view(request):
    if request.method == "POST":
        try:
            round_id = request.POST.get("round_id")
            round_obj = get_object_or_404(Round, id=round_id)

            # Update round fields
            round_obj.name = request.POST.get("name")
            round_obj.start = request.POST.get("start")

            # Parse duration strings
            def parse_duration(duration_str):
                if ":" in duration_str:
                    parts = duration_str.split(":")
                    if len(parts) == 3:  # HH:MM:SS
                        hours, minutes, seconds = map(int, parts)
                        return dt.timedelta(
                            hours=hours, minutes=minutes, seconds=seconds
                        )
                    elif len(parts) == 2:  # MM:SS
                        minutes, seconds = map(int, parts)
                        return dt.timedelta(minutes=minutes, seconds=seconds)
                return dt.timedelta(0)

            round_obj.duration = parse_duration(request.POST.get("duration"))
            round_obj.pitlane_open_after = parse_duration(
                request.POST.get("pitlane_open_after")
            )
            round_obj.pitlane_close_before = parse_duration(
                request.POST.get("pitlane_close_before")
            )

            # Update other fields
            round_obj.change_lanes = int(request.POST.get("change_lanes"))
            round_obj.limit_time = request.POST.get("limit_time")
            round_obj.limit_value = int(request.POST.get("limit_value"))
            round_obj.required_changes = int(request.POST.get("required_changes"))

            round_obj.limit_method = request.POST.get("limit_method")

            # Handle weight penalty JSON field
            weight_penalty_json = request.POST.get("weight_penalty", '[">=", [0, 0]]')
            try:
                weight_penalty = json.loads(weight_penalty_json)
                round_obj.weight_penalty = weight_penalty
            except json.JSONDecodeError:
                return JsonResponse(
                    {"success": False, "error": "Invalid weight penalty format"}
                )

            # Handle lap-based timing toggle
            lap_based = request.POST.get("lap_based") == "on"
            was_legacy = round_obj.uses_legacy_session_model

            if lap_based:
                round_obj.uses_legacy_session_model = False
                round_obj.save()
                ending_mode = request.POST.get("ending_mode", "CROSS_AFTER_TIME")
                ok, err = _create_qualifying_races(round_obj, request.POST, ending_mode)
                if not ok:
                    return JsonResponse({"success": False, "error": err})
            elif not lap_based and not was_legacy:
                # Disabling lap-based: clean up Race objects
                if Race.objects.filter(round=round_obj, started__isnull=False).exists():
                    return JsonResponse(
                        {
                            "success": False,
                            "error": "Cannot disable transponder timing: a race has already started.",
                        }
                    )
                QualifyingKnockoutRule.objects.filter(
                    qualifying_race__round=round_obj
                ).delete()
                Race.objects.filter(round=round_obj).delete()
                round_obj.uses_legacy_session_model = True
                round_obj.save()
            else:
                round_obj.save()
            return JsonResponse({"success": True})
        except Exception as e:
            return JsonResponse({"success": False, "error": str(e)})

    # GET request - show the form
    championships = Championship.objects.all().order_by("-start")

    context = {
        "championships": championships,
        "organiser_logo": get_organiser_logo(current_round()),
        "sponsors_logos": get_sponsor_logos(current_round()),
    }
    return render(request, "pages/edit_round.html", context)


@login_required
@user_passes_test(is_admin_user)
def get_championship_rounds(request, championship_id):
    """API endpoint to get rounds for a championship. If ?only_not_ready=1, only return not ready rounds."""
    try:
        championship = get_object_or_404(Championship, id=championship_id)
        only_not_ready = request.GET.get("only_not_ready") == "1"
        if only_not_ready:
            rounds = Round.objects.filter(
                championship=championship, ready=False
            ).order_by("start")
        else:
            rounds = Round.objects.filter(championship=championship).order_by("start")

        def format_duration(td):
            """Format timedelta as HH:MM:SS with leading zeros"""
            total_seconds = int(td.total_seconds())
            hours = total_seconds // 3600
            minutes = (total_seconds % 3600) // 60
            seconds = total_seconds % 60
            return f"{hours:02d}:{minutes:02d}:{seconds:02d}"

        def format_minutes_seconds(td):
            """Format timedelta as MM:SS with leading zeros"""
            total_seconds = int(td.total_seconds())
            minutes = total_seconds // 60
            seconds = total_seconds % 60
            return f"{minutes:02d}:{seconds:02d}"

        rounds_data = []
        for round_obj in rounds:
            rounds_data.append(
                {
                    "id": round_obj.id,
                    "name": round_obj.name,
                    "start": round_obj.start.isoformat(),
                    "duration": format_duration(round_obj.duration),
                    "change_lanes": round_obj.change_lanes,
                    "pitlane_open_after": format_minutes_seconds(
                        round_obj.pitlane_open_after
                    ),
                    "pitlane_close_before": format_minutes_seconds(
                        round_obj.pitlane_close_before
                    ),
                    "limit_time": round_obj.limit_time,
                    "limit_method": round_obj.limit_method,
                    "limit_value": round_obj.limit_value,
                    "limit_time_min": format_minutes_seconds(round_obj.limit_time_min),
                    "required_changes": round_obj.required_changes,
                    "weight_penalty": round_obj.weight_penalty or [">=", [0, 0]],
                    "ready": round_obj.ready,
                    "uses_legacy_session_model": round_obj.uses_legacy_session_model,
                    "ending_mode": getattr(round_obj.races.first(), "ending_mode", ""),
                    **_get_qualifying_info(round_obj),
                }
            )

        return JsonResponse(
            {"rounds": rounds_data, "total": len(rounds_data)}, safe=False
        )
    except Exception as e:
        return JsonResponse({"error": str(e)}, status=400)


@login_required
@user_passes_test(is_admin_user)
def transponder_management_view(request):
    """CRUD management for transponders."""
    if request.method == "POST":
        try:
            action = request.POST.get("action")

            if action == "create_transponder":
                transponder_id = request.POST.get("transponder_id", "").strip()
                description = request.POST.get("description", "").strip()
                active = request.POST.get("active") == "on"
                if not transponder_id:
                    return JsonResponse(
                        {"success": False, "error": "Transponder ID is required"}
                    )
                if Transponder.objects.filter(transponder_id=transponder_id).exists():
                    return JsonResponse(
                        {"success": False, "error": "Transponder ID already exists"}
                    )
                Transponder.objects.create(
                    transponder_id=transponder_id,
                    description=description,
                    active=active,
                )
                return JsonResponse(
                    {"success": True, "message": "Transponder created successfully"}
                )

            elif action == "edit_transponder":
                pk = request.POST.get("transponder_pk")
                transponder = get_object_or_404(Transponder, pk=pk)
                new_id = request.POST.get("transponder_id", "").strip()
                if new_id and new_id != transponder.transponder_id:
                    if Transponder.objects.filter(transponder_id=new_id).exists():
                        return JsonResponse(
                            {
                                "success": False,
                                "error": "Transponder ID already exists",
                            }
                        )
                    transponder.transponder_id = new_id
                transponder.description = request.POST.get("description", "").strip()
                transponder.active = request.POST.get("active") == "on"
                transponder.save()
                return JsonResponse(
                    {"success": True, "message": "Transponder updated successfully"}
                )

            elif action == "delete_transponder":
                pk = request.POST.get("transponder_pk")
                transponder = get_object_or_404(Transponder, pk=pk)
                # Block deletion if assigned to a non-ended race
                active_assignments = RaceTransponderAssignment.objects.filter(
                    transponder=transponder,
                    race__ended__isnull=True,
                )
                if active_assignments.exists():
                    return JsonResponse(
                        {
                            "success": False,
                            "error": "Cannot delete: transponder is assigned to an active race",
                        }
                    )
                transponder.delete()
                return JsonResponse(
                    {"success": True, "message": "Transponder deleted successfully"}
                )

            else:
                return JsonResponse(
                    {"success": False, "error": "Unknown action"}, status=400
                )
        except Exception as e:
            return JsonResponse({"success": False, "error": str(e)}, status=400)

    # GET: list all transponders
    transponders = Transponder.objects.all().order_by("transponder_id")
    context = {
        "transponders": transponders,
        "organiser_logo": get_organiser_logo(current_round()),
        "sponsors_logos": get_sponsor_logos(current_round()),
    }
    return render(request, "pages/transponder_management.html", context)


@login_required
@user_passes_test(is_admin_user)
def penalty_management_view(request):
    if request.method == "POST":
        try:
            action = request.POST.get("action")

            if action == "create_penalty":
                name = request.POST.get("name")
                description = request.POST.get("description", "")

                penalty = Penalty.objects.create(name=name, description=description)

                if "illustration" in request.FILES:
                    penalty.illustration = request.FILES["illustration"]
                    penalty.save()

                return JsonResponse(
                    {"success": True, "message": "Penalty created successfully"}
                )

            elif action == "edit_penalty":
                penalty_id = request.POST.get("penalty_id")
                penalty = get_object_or_404(Penalty, id=penalty_id)

                penalty.name = request.POST.get("name")
                penalty.description = request.POST.get("description", "")

                if "illustration" in request.FILES:
                    penalty.illustration = request.FILES["illustration"]

                penalty.save()
                return JsonResponse(
                    {"success": True, "message": "Penalty updated successfully"}
                )

            elif action == "delete_penalty":
                penalty_id = request.POST.get("penalty_id")
                penalty = get_object_or_404(Penalty, id=penalty_id)
                penalty.delete()
                return JsonResponse(
                    {"success": True, "message": "Penalty deleted successfully"}
                )

        except Exception as e:
            return JsonResponse({"success": False, "error": str(e)})

    # GET request - show the penalties
    penalties = Penalty.objects.all().order_by("name")
    context = {
        "penalties": penalties,
        "organiser_logo": get_organiser_logo(current_round()),
        "sponsors_logos": get_sponsor_logos(current_round()),
    }
    return render(request, "pages/penalty_management.html", context)


@login_required
@user_passes_test(is_admin_user)
def sponsor_management_view(request):
    if request.method == "POST":
        try:
            action = request.POST.get("action")

            if action == "create_logo":
                name = request.POST.get("name")
                championship_id = request.POST.get("championship_id")

                # Validate name
                if name not in ["organiser logo", "sponsor logo"]:
                    return JsonResponse(
                        {
                            "success": False,
                            "error": "Logo name must be 'organiser logo' or 'sponsor logo'",
                        }
                    )

                # Handle championship
                championship = None
                if championship_id:
                    championship = get_object_or_404(Championship, id=championship_id)

                # Check for organiser logo uniqueness constraint (only for organiser logos)
                if name == "organiser logo":
                    if Logo.objects.filter(
                        name="organiser logo", championship=championship
                    ).exists():
                        return JsonResponse(
                            {
                                "success": False,
                                "error": "Organiser logo already exists for this championship",
                            }
                        )

                # Create logo
                logo = Logo.objects.create(name=name, championship=championship)

                if "image" in request.FILES:
                    logo.image = request.FILES["image"]
                    logo.save()
                else:
                    return JsonResponse(
                        {"success": False, "error": "Image file is required"}
                    )

                return JsonResponse(
                    {"success": True, "message": "Logo created successfully"}
                )

            elif action == "edit_logo":
                logo_id = request.POST.get("logo_id")
                logo = get_object_or_404(Logo, id=logo_id)

                name = request.POST.get("name")
                championship_id = request.POST.get("championship_id")

                # Validate name
                if name not in ["organiser logo", "sponsor logo"]:
                    return JsonResponse(
                        {
                            "success": False,
                            "error": "Logo name must be 'organiser logo' or 'sponsor logo'",
                        }
                    )

                # Handle championship
                championship = None
                if championship_id:
                    championship = get_object_or_404(Championship, id=championship_id)

                # Check for organiser logo uniqueness constraint (exclude current logo, only for organiser logos)
                if name == "organiser logo":
                    if (
                        Logo.objects.filter(
                            name="organiser logo", championship=championship
                        )
                        .exclude(id=logo.id)
                        .exists()
                    ):
                        return JsonResponse(
                            {
                                "success": False,
                                "error": "Organiser logo already exists for this championship",
                            }
                        )

                logo.name = name
                logo.championship = championship

                if "image" in request.FILES:
                    logo.image = request.FILES["image"]

                logo.save()
                return JsonResponse(
                    {"success": True, "message": "Logo updated successfully"}
                )

            elif action == "delete_logo":
                logo_id = request.POST.get("logo_id")
                logo = get_object_or_404(Logo, id=logo_id)
                logo.delete()
                return JsonResponse(
                    {"success": True, "message": "Logo deleted successfully"}
                )

        except Exception as e:
            return JsonResponse({"success": False, "error": str(e)})

    # GET request - show the logos
    logos = Logo.objects.all().order_by("name", "championship__name")
    championships = Championship.objects.all().order_by("name")
    context = {
        "logos": logos,
        "championships": championships,
        "organiser_logo": get_organiser_logo(current_round()),
        "sponsors_logos": get_sponsor_logos(current_round()),
    }
    return render(request, "pages/sponsor_management.html", context)


@login_required
@user_passes_test(is_admin_user)
def get_available_penalties(request, championship_id):
    """API endpoint to get penalties not yet configured for a championship."""
    try:
        championship = get_object_or_404(Championship, id=championship_id)

        # Get penalties that are already configured for this championship
        configured_penalty_ids = ChampionshipPenalty.objects.filter(
            championship=championship
        ).values_list("penalty_id", flat=True)

        # Get all penalties not in the configured list
        available_penalties = Penalty.objects.exclude(
            id__in=configured_penalty_ids
        ).order_by("name")

        penalties_data = [
            {"id": penalty.id, "name": penalty.name, "description": penalty.description}
            for penalty in available_penalties
        ]

        return JsonResponse({"penalties": penalties_data})
    except Exception as e:
        return JsonResponse({"error": str(e)}, status=400)


@login_required
def get_stop_and_go_penalties(request, round_id):
    """API endpoint to get Stop & Go penalties for a specific round's championship."""
    try:
        round_obj = get_object_or_404(Round, id=round_id)
        championship = round_obj.championship

        # Get Stop & Go and Self Stop & Go penalties for this championship
        stop_go_penalties = (
            ChampionshipPenalty.objects.filter(
                championship=championship,
                sanction__in=["S", "D"],  # Stop & Go and Self Stop & Go
            )
            .select_related("penalty")
            .order_by("penalty__name")
        )

        penalties_data = [
            {
                "id": cp.id,
                "penalty_id": cp.penalty.id,
                "penalty_name": cp.penalty.name,
                "penalty_description": cp.penalty.description,
                "sanction": cp.sanction,
                "value": cp.value,
                "option": cp.option,
                "option_display": cp.get_option_display(),
            }
            for cp in stop_go_penalties
        ]

        return JsonResponse({"penalties": penalties_data})
    except Exception as e:
        return JsonResponse({"error": str(e)}, status=400)


@login_required
@csrf_exempt
def create_round_penalty(request):
    """API endpoint to create a RoundPenalty record."""
    if request.method == "POST":
        try:
            data = json.loads(request.body)

            round_id = data.get("round_id")
            offender_id = data.get("offender_id")
            victim_id = data.get("victim_id")
            championship_penalty_id = data.get("championship_penalty_id")
            value = data.get("value")

            round_obj = get_object_or_404(Round, id=round_id)
            offender = get_object_or_404(round_team, id=offender_id)
            championship_penalty = get_object_or_404(
                ChampionshipPenalty, id=championship_penalty_id
            )

            victim = None
            if victim_id:
                victim = get_object_or_404(round_team, id=victim_id)

            # Create RoundPenalty record
            round_penalty = RoundPenalty.objects.create(
                round=round_obj,
                offender=offender,
                victim=victim,
                penalty=championship_penalty,
                value=value,
                imposed=dt.datetime.now(),
                served=None,  # Will be set when penalty is served
            )

            return JsonResponse(
                {
                    "success": True,
                    "penalty_id": round_penalty.id,
                    "message": "Penalty recorded successfully",
                }
            )

        except Exception as e:
            return JsonResponse({"success": False, "error": str(e)}, status=400)

    return JsonResponse({"error": "Only POST method allowed"}, status=405)


@login_required
@csrf_exempt
def update_penalty_served(request):
    """API endpoint to update RoundPenalty served timestamp."""
    if request.method == "POST":
        try:
            data = json.loads(request.body)
            penalty_id = data.get("penalty_id")

            round_penalty = get_object_or_404(RoundPenalty, id=penalty_id)
            round_penalty.served = dt.datetime.now()
            round_penalty.save()

            return JsonResponse(
                {"success": True, "message": "Penalty served timestamp updated"}
            )

        except Exception as e:
            return JsonResponse({"success": False, "error": str(e)}, status=400)

    return JsonResponse({"error": "Only POST method allowed"}, status=405)


@login_required
@user_passes_test(is_admin_user)
def get_championship_penalties(request, championship_id):
    """API endpoint to get penalties configured for a championship."""
    try:
        championship = get_object_or_404(Championship, id=championship_id)

        championship_penalties = (
            ChampionshipPenalty.objects.filter(championship=championship)
            .select_related("penalty")
            .order_by("penalty__name")
        )

        penalties_data = [
            {
                "id": cp.id,
                "penalty_id": cp.penalty.id,
                "penalty_name": cp.penalty.name,
                "penalty_description": cp.penalty.description,
                "sanction": cp.sanction,
                "sanction_display": cp.get_sanction_display(),
                "value": cp.value,
                "option": cp.option,
                "option_display": cp.get_option_display(),
            }
            for cp in championship_penalties
        ]

        return JsonResponse({"penalties": penalties_data})
    except Exception as e:
        return JsonResponse({"error": str(e)}, status=400)


@login_required
def get_stop_and_go_penalties(request, round_id):
    """API endpoint to get Stop & Go penalties for a specific round's championship."""
    try:
        round_obj = get_object_or_404(Round, id=round_id)
        championship = round_obj.championship

        # Get Stop & Go and Self Stop & Go penalties for this championship
        stop_go_penalties = (
            ChampionshipPenalty.objects.filter(
                championship=championship,
                sanction__in=["S", "D"],  # Stop & Go and Self Stop & Go
            )
            .select_related("penalty")
            .order_by("penalty__name")
        )

        penalties_data = [
            {
                "id": cp.id,
                "penalty_id": cp.penalty.id,
                "penalty_name": cp.penalty.name,
                "penalty_description": cp.penalty.description,
                "sanction": cp.sanction,
                "value": cp.value,
                "option": cp.option,
                "option_display": cp.get_option_display(),
            }
            for cp in stop_go_penalties
        ]

        return JsonResponse({"penalties": penalties_data})
    except Exception as e:
        return JsonResponse({"error": str(e)}, status=400)


@login_required
@csrf_exempt
def create_round_penalty(request):
    """API endpoint to create a RoundPenalty record."""
    if request.method == "POST":
        try:
            data = json.loads(request.body)

            round_id = data.get("round_id")
            offender_id = data.get("offender_id")
            victim_id = data.get("victim_id")
            championship_penalty_id = data.get("championship_penalty_id")
            value = data.get("value")

            round_obj = get_object_or_404(Round, id=round_id)
            offender = get_object_or_404(round_team, id=offender_id)
            championship_penalty = get_object_or_404(
                ChampionshipPenalty, id=championship_penalty_id
            )

            victim = None
            if victim_id:
                victim = get_object_or_404(round_team, id=victim_id)

            # Create RoundPenalty record
            round_penalty = RoundPenalty.objects.create(
                round=round_obj,
                offender=offender,
                victim=victim,
                penalty=championship_penalty,
                value=value,
                imposed=dt.datetime.now(),
                served=None,  # Will be set when penalty is served
            )

            return JsonResponse(
                {
                    "success": True,
                    "penalty_id": round_penalty.id,
                    "message": "Penalty recorded successfully",
                }
            )

        except Exception as e:
            return JsonResponse({"success": False, "error": str(e)}, status=400)

    return JsonResponse({"error": "Only POST method allowed"}, status=405)


@login_required
@csrf_exempt
def update_penalty_served(request):
    """API endpoint to update RoundPenalty served timestamp."""
    if request.method == "POST":
        try:
            data = json.loads(request.body)
            penalty_id = data.get("penalty_id")

            round_penalty = get_object_or_404(RoundPenalty, id=penalty_id)
            round_penalty.served = dt.datetime.now()
            round_penalty.save()

            return JsonResponse(
                {"success": True, "message": "Penalty served timestamp updated"}
            )

        except Exception as e:
            return JsonResponse({"success": False, "error": str(e)}, status=400)

    return JsonResponse({"error": "Only POST method allowed"}, status=405)


@login_required
def get_laps_penalties(request, round_id):
    """API endpoint to get Laps penalties for a specific round's championship."""
    try:
        round_obj = get_object_or_404(Round, id=round_id)
        championship = round_obj.championship

        # Get only Laps penalties for this championship
        laps_penalties = (
            ChampionshipPenalty.objects.filter(
                championship=championship, sanction="L"  # Laps
            )
            .select_related("penalty")
            .order_by("penalty__name")
        )

        penalties_data = [
            {
                "id": cp.id,
                "penalty_id": cp.penalty.id,
                "penalty_name": cp.penalty.name,
                "penalty_description": cp.penalty.description,
                "value": cp.value,
                "option": cp.option,
                "option_display": cp.get_option_display(),
            }
            for cp in laps_penalties
        ]

        return JsonResponse({"penalties": penalties_data})
    except Exception as e:
        return JsonResponse({"error": str(e)}, status=400)


@csrf_exempt
def queue_penalty(request):
    """API endpoint to queue a Stop & Go penalty."""
    if request.method == "POST":
        try:
            data = json.loads(request.body)

            round_id = data.get("round_id")
            offender_id = data.get("offender_id")
            victim_id = data.get("victim_id")
            championship_penalty_id = data.get("championship_penalty_id")
            value = data.get("value")

            round_obj = get_object_or_404(Round, id=round_id)
            offender = get_object_or_404(round_team, id=offender_id)
            championship_penalty = get_object_or_404(
                ChampionshipPenalty, id=championship_penalty_id
            )

            # Validate that this is a Stop & Go penalty
            if championship_penalty.sanction not in ["S", "D"]:
                return JsonResponse(
                    {
                        "success": False,
                        "error": "Only Stop & Go penalties can be queued",
                    },
                    status=400,
                )

            victim = None
            if victim_id:
                victim = get_object_or_404(round_team, id=victim_id)

            # Check if queue was empty before adding new penalty
            was_queue_empty = not PenaltyQueue.objects.filter(
                round_penalty__round_id=round_id
            ).exists()

            # Create RoundPenalty
            round_penalty = RoundPenalty.objects.create(
                round=round_obj,
                offender=offender,
                victim=victim,
                penalty=championship_penalty,
                value=value,
                imposed=dt.datetime.now(),
            )

            # Create PenaltyQueue entry
            queue_entry = PenaltyQueue.objects.create(
                round_penalty=round_penalty, timestamp=dt.datetime.now()
            )

            # Signal penalty queue system
            # Only triggers immediately if queue was empty (0→1)
            if was_queue_empty:
                # Trigger first penalty immediately using channels
                from channels.layers import get_channel_layer
                from asgiref.sync import async_to_sync

                channel_layer = get_channel_layer()
                async_to_sync(channel_layer.group_send)(
                    "stopandgo",
                    {
                        "type": "penalty_required",
                        "team": offender.team.number,
                        "duration": value,
                        "penalty_id": round_penalty.id,
                    },
                )

            return JsonResponse(
                {
                    "success": True,
                    "penalty_id": round_penalty.id,
                    "queue_id": queue_entry.id,
                }
            )

        except json.JSONDecodeError:
            return JsonResponse({"success": False, "error": "Invalid JSON"}, status=400)
        except Exception as e:
            return JsonResponse({"success": False, "error": str(e)}, status=500)

    return JsonResponse({"success": False, "error": "Method not allowed"}, status=405)


@csrf_exempt
def get_penalty_queue_status(request, round_id):
    """API endpoint to get current penalty queue status."""
    try:
        active_penalty = PenaltyQueue.get_next_penalty(round_id)

        # Count total penalties in queue for this round
        queue_count = PenaltyQueue.objects.filter(
            round_penalty__round_id=round_id
        ).count()

        # Get serving team number if there's an active penalty
        serving_team = None
        if active_penalty and active_penalty.round_penalty.offender:
            serving_team = active_penalty.round_penalty.offender.team.number

        response_data = {
            "queue_count": queue_count,
            "serving_team": serving_team,
        }

        if active_penalty:
            response_data["active_penalty"] = {
                "queue_id": active_penalty.id,
                "penalty_id": active_penalty.round_penalty.id,
                "team_number": active_penalty.round_penalty.offender.team.number,
                "penalty_name": active_penalty.round_penalty.penalty.penalty.name,
                "value": active_penalty.round_penalty.value,
                "timestamp": active_penalty.timestamp.isoformat(),
            }
        else:
            response_data["active_penalty"] = None

        return JsonResponse(response_data)

    except Exception as e:
        return JsonResponse({"error": str(e)}, status=400)


@csrf_exempt
def serve_penalty(request):
    """API endpoint to mark a penalty as served."""
    if request.method == "POST":
        try:
            data = json.loads(request.body)
            round_id = data.get("round_id")

            if not round_id:
                return JsonResponse(
                    {"success": False, "error": "round_id is required"}, status=400
                )

            # Get the current active penalty (first in queue order)
            queue_entry = PenaltyQueue.get_next_penalty(round_id)
            if not queue_entry:
                return JsonResponse(
                    {"success": False, "error": "No active penalty found"}, status=404
                )

            # Mark penalty as served
            queue_entry.round_penalty.served = dt.datetime.now()
            queue_entry.round_penalty.save()

            # Remove from queue
            round_id = queue_entry.round_penalty.round.id
            queue_entry.delete()

            # Reset the station and handle queue progression
            from channels.layers import get_channel_layer
            from asgiref.sync import async_to_sync

            channel_layer = get_channel_layer()

            # Send reset to station to clear display
            async_to_sync(channel_layer.group_send)(
                "stopandgo",
                {
                    "type": "reset_station",
                },
            )

            # Then signal queue progression
            async_to_sync(channel_layer.group_send)(
                "stopandgo",
                {
                    "type": "penalty_cancelled",  # Use same handler as cancel for queue progression
                    "round_id": round_id,
                },
            )

            return JsonResponse({"success": True})

        except json.JSONDecodeError:
            return JsonResponse({"success": False, "error": "Invalid JSON"}, status=400)
        except Exception as e:
            return JsonResponse({"success": False, "error": str(e)}, status=500)

    return JsonResponse({"success": False, "error": "Method not allowed"}, status=405)


@csrf_exempt
def cancel_penalty(request):
    """API endpoint to cancel a penalty (remove both penalty and queue entry)."""
    if request.method == "POST":
        try:
            data = json.loads(request.body)
            queue_id = data.get("queue_id")

            queue_entry = get_object_or_404(PenaltyQueue, id=queue_id)
            round_id = queue_entry.round_penalty.round.id

            # Delete both penalty and queue entry
            round_penalty = queue_entry.round_penalty
            queue_entry.delete()
            round_penalty.delete()

            # Reset the station and handle queue progression
            from channels.layers import get_channel_layer
            from asgiref.sync import async_to_sync

            channel_layer = get_channel_layer()

            # Send reset to station first
            async_to_sync(channel_layer.group_send)(
                "stopandgo",
                {
                    "type": "reset_station",
                },
            )

            # Then signal queue progression
            async_to_sync(channel_layer.group_send)(
                "stopandgo",
                {
                    "type": "penalty_cancelled",
                    "round_id": round_id,
                },
            )

            return JsonResponse({"success": True})

        except json.JSONDecodeError:
            return JsonResponse({"success": False, "error": "Invalid JSON"}, status=400)
        except Exception as e:
            return JsonResponse({"success": False, "error": str(e)}, status=500)

    return JsonResponse({"success": False, "error": "Method not allowed"}, status=405)


@csrf_exempt
def delay_penalty(request):
    """API endpoint to delay a penalty (move to end of queue)."""
    if request.method == "POST":
        try:
            data = json.loads(request.body)
            queue_id = data.get("queue_id")

            queue_entry = get_object_or_404(PenaltyQueue, id=queue_id)
            round_id = queue_entry.round_penalty.round.id

            # Move to end of queue
            queue_entry.delay_penalty()

            # Check if this was a delayed penalty and apply "ignoring s&g" penalty
            # as specified in requirements
            round_obj = queue_entry.round_penalty.round
            try:
                ignoring_sg_penalty = ChampionshipPenalty.objects.get(
                    championship=round_obj.championship, penalty__name="ignoring s&g"
                )

                # Apply ignoring s&g penalty to the offending team
                RoundPenalty.objects.create(
                    round=round_obj,
                    offender=queue_entry.round_penalty.offender,
                    victim=None,
                    penalty=ignoring_sg_penalty,
                    value=ignoring_sg_penalty.value,
                    imposed=dt.datetime.now(),
                )
            except ChampionshipPenalty.DoesNotExist:
                # No "ignoring s&g" penalty configured
                pass

            # Reset the station and handle queue progression
            from channels.layers import get_channel_layer
            from asgiref.sync import async_to_sync

            channel_layer = get_channel_layer()

            # Send reset to station first
            async_to_sync(channel_layer.group_send)(
                "stopandgo",
                {
                    "type": "reset_station",
                },
            )

            # Then signal queue progression
            async_to_sync(channel_layer.group_send)(
                "stopandgo",
                {
                    "type": "penalty_delayed",
                    "round_id": round_id,
                },
            )

            return JsonResponse({"success": True})

        except json.JSONDecodeError:
            return JsonResponse({"success": False, "error": "Invalid JSON"}, status=400)
        except Exception as e:
            return JsonResponse({"success": False, "error": str(e)}, status=500)

    return JsonResponse({"success": False, "error": "Method not allowed"}, status=405)


# Note: Penalty queue timing and next penalty triggering will be handled
# by the StopAndGoConsumer when it receives penalty state updates


def get_organiser_logo(round_obj):
    """
    Retrieve the organiser logo for a given round.

    Priority order:
    1. Logo with name "organiser logo" for the round's championship
    2. Logo with name "organiser logo" for NULL championship (global)
    3. None if no matching logo found

    Args:
        round_obj: Round instance

    Returns:
        Logo instance or None
    """
    if not round_obj:
        return None

    try:
        # First try to get championship-specific organiser logo
        return Logo.objects.get(
            name="organiser logo", championship=round_obj.championship
        )
    except Logo.DoesNotExist:
        try:
            # Fallback to global organiser logo (NULL championship)
            return Logo.objects.get(name="organiser logo", championship__isnull=True)
        except Logo.DoesNotExist:
            # No organiser logo found
            return None


def get_sponsor_logos(round_obj):
    """
    Retrieve sponsor logos for a given round.

    Priority order:
    1. All logos with name "sponsor logo" for the round's championship
    2. All logos with name "sponsor logo" for NULL championship (global defaults)
    3. Single gokartrace logo if no sponsor logos found

    Args:
        round_obj: Round instance

    Returns:
        QuerySet of Logo instances or list with single gokartrace logo dict
    """
    if round_obj:
        # First try to get championship-specific sponsor logos
        championship_sponsors = Logo.objects.filter(
            name="sponsor logo", championship=round_obj.championship
        )
        if championship_sponsors.exists():
            return championship_sponsors

    # Fallback to global sponsor logos (NULL championship)
    global_sponsors = Logo.objects.filter(
        name="sponsor logo", championship__isnull=True
    )
    if global_sponsors.exists():
        return global_sponsors

    # If no sponsor logos found, return gokartrace logo as fallback
    return [
        {"name": "GoKartRace", "image": {"url": "/static/logos/gokartrace-logo.svg"}}
    ]


# ============================================================
# Grid Management Views (Phase 4 - Qualifying & Grid System)
# ============================================================


@login_required
@user_passes_test(is_admin_user)
def race_grid_management(request, race_id):
    """Grid management view for race directors"""
    race = get_object_or_404(Race, id=race_id)

    # Get current grid positions (ordered by position)
    grid_positions = GridPosition.objects.filter(race=race).order_by("position")

    # Get teams not yet assigned to grid
    assigned_team_ids = grid_positions.values_list("team_id", flat=True)
    unassigned_teams = race.get_all_teams().exclude(id__in=assigned_team_ids)

    context = {
        "race": race,
        "grid_positions": grid_positions,
        "unassigned_teams": unassigned_teams,
        "is_locked": race.grid_locked,
    }

    return render(request, "pages/race_grid_management.html", context)


@login_required
@user_passes_test(is_admin_user)
@csrf_exempt
def update_grid_position(request, race_id):
    """API endpoint to update a single grid position"""
    if request.method != "POST":
        return JsonResponse({"error": "Only POST method allowed"}, status=405)

    try:
        data = json.loads(request.body)
        race = get_object_or_404(Race, id=race_id)

        if race.grid_locked:
            return JsonResponse(
                {"success": False, "error": "Grid is locked"}, status=400
            )

        team_id = data.get("team_id")
        new_position = data.get("position")

        team = get_object_or_404(round_team, id=team_id)

        GridPosition.objects.update_or_create(
            race=race,
            team=team,
            defaults={
                "position": new_position,
                "source": "MANUAL",
                "manually_overridden": True,
                "override_reason": data.get("reason", "Manual adjustment"),
            },
        )

        return JsonResponse({"success": True})

    except Exception as e:
        return JsonResponse({"success": False, "error": str(e)}, status=400)


@login_required
@user_passes_test(is_admin_user)
@csrf_exempt
def reorder_grid_positions(request, race_id):
    """API endpoint to reorder multiple grid positions (drag & drop)"""
    if request.method != "POST":
        return JsonResponse({"error": "Only POST method allowed"}, status=405)

    try:
        data = json.loads(request.body)
        race = get_object_or_404(Race, id=race_id)

        if race.grid_locked:
            return JsonResponse(
                {"success": False, "error": "Grid is locked"}, status=400
            )

        # data should be list of {team_id, position}
        positions_data = data.get("positions", [])

        for item in positions_data:
            team_id = item.get("team_id")
            position = item.get("position")

            team = get_object_or_404(round_team, id=team_id)

            GridPosition.objects.update_or_create(
                race=race,
                team=team,
                defaults={
                    "position": position,
                    "source": "MANUAL",
                    "manually_overridden": True,
                    "override_reason": "Drag and drop reorder",
                },
            )

        return JsonResponse({"success": True})

    except Exception as e:
        return JsonResponse({"success": False, "error": str(e)}, status=400)


@login_required
@user_passes_test(is_admin_user)
@require_POST
def lock_grid(request, race_id):
    """Lock grid positions"""
    race = get_object_or_404(Race, id=race_id)
    race.lock_grid()
    messages.success(request, "Grid positions locked successfully")
    return redirect("race_grid_management", race_id=race_id)


@login_required
@user_passes_test(is_admin_user)
@require_POST
def unlock_grid(request, race_id):
    """Unlock grid positions"""
    race = get_object_or_404(Race, id=race_id)
    race.unlock_grid()
    messages.success(request, "Grid positions unlocked successfully")
    return redirect("race_grid_management", race_id=race_id)


@login_required
@user_passes_test(is_admin_user)
@require_POST
def reset_grid_to_auto(request, race_id):
    """Reset grid to auto-assigned positions"""
    race = get_object_or_404(Race, id=race_id)

    if race.grid_locked:
        messages.error(request, "Cannot reset - grid is locked")
        return redirect("race_grid_management", race_id=race_id)

    race.reset_grid_to_auto()
    messages.success(request, "Grid positions reset to auto-assigned")
    return redirect("race_grid_management", race_id=race_id)


@login_required
@user_passes_test(is_admin_user)
@require_POST
def auto_assign_from_qualifying(request, race_id):
    """Auto-assign grid from qualifying results"""
    race = get_object_or_404(Race, id=race_id)

    if race.grid_locked:
        messages.error(request, "Cannot auto-assign - grid is locked")
        return redirect("race_grid_management", race_id=race_id)

    if not race.depends_on_race:
        messages.error(request, "No qualifying race configured")
        return redirect("race_grid_management", race_id=race_id)

    race.auto_assign_grid_positions(source_type="QUALIFYING")
    messages.success(request, "Grid assigned from qualifying results")
    return redirect("race_grid_management", race_id=race_id)


@login_required
@user_passes_test(is_admin_user)
@require_POST
def auto_assign_from_championship(request, race_id):
    """Auto-assign grid from championship standings"""
    race = get_object_or_404(Race, id=race_id)

    if race.grid_locked:
        messages.error(request, "Cannot auto-assign - grid is locked")
        return redirect("race_grid_management", race_id=race_id)

    race.auto_assign_grid_positions(source_type="CHAMPIONSHIP")
    messages.success(request, "Grid assigned from championship standings")
    return redirect("race_grid_management", race_id=race_id)


# ============================================================
# Leaderboard Views (Phase 5 - Leaderboard & Displays)
# ============================================================


def public_leaderboard(request, race_id):
    """Public full-screen leaderboard display"""
    race = get_object_or_404(Race, id=race_id)

    # Get initial standings or pre-race team list
    standings = race.calculate_race_standings() if race.started else []
    teams = race.get_all_teams().order_by("team__number") if not race.started else []

    context = {
        "race": race,
        "standings": standings,
        "teams": teams,
        "effective_lap_count": race.get_effective_lap_count(),
        "race_time_limit_seconds": int(race.get_effective_time_limit().total_seconds()),
        "race_started_epoch": int(race.started.timestamp()) if race.started else None,
    }

    return render(request, "pages/public_leaderboard.html", context)


# ============================================================
# Lap Management Views (Phase 6 - Lap Splitting & Suspicious Lap Detection)
# ============================================================


@login_required
@user_passes_test(is_admin_user)
def race_lap_management(request, race_id):
    """Lap management view for race directors"""
    race = get_object_or_404(Race, id=race_id)

    context = {
        "race": race,
    }

    return render(request, "pages/race_lap_management.html", context)


@login_required
@user_passes_test(is_admin_user)
def get_race_laps(request, race_id):
    """API endpoint to get all laps for a race"""
    race = get_object_or_404(Race, id=race_id)

    laps = []
    for team in race.get_all_teams():
        team_laps = (
            LapCrossing.objects.filter(race=race, team=team)
            .order_by("lap_number")
            .values(
                "id",
                "lap_number",
                "crossing_time",
                "lap_time",
                "is_valid",
                "is_suspicious",
                "was_split",
                "counted_during_suspension",
            )
        )

        for lap in team_laps:
            laps.append(
                {
                    "id": lap["id"],
                    "team_id": team.id,
                    "team_number": team.number,
                    "team_name": team.name,
                    "lap_number": lap["lap_number"],
                    "crossing_time": lap["crossing_time"].isoformat(),
                    "lap_time": str(lap["lap_time"]).split(".")[0]
                    if lap["lap_time"]
                    else "—",
                    "lap_time_seconds": lap["lap_time"].total_seconds()
                    if lap["lap_time"]
                    else None,
                    "is_valid": lap["is_valid"],
                    "is_suspicious": lap["is_suspicious"],
                    "was_split": lap["was_split"],
                    "counted_during_suspension": lap["counted_during_suspension"],
                }
            )

    return JsonResponse({"laps": laps})


@login_required
@user_passes_test(is_admin_user)
@csrf_exempt
@require_POST
def split_lap(request, crossing_id):
    """Split a suspicious lap into two laps"""
    try:
        crossing = get_object_or_404(LapCrossing, id=crossing_id)

        # Find previous crossing
        prev_crossing = (
            LapCrossing.objects.filter(
                race=crossing.race,
                team=crossing.team,
                lap_number__lt=crossing.lap_number,
            )
            .order_by("-lap_number")
            .first()
        )

        if not prev_crossing:
            return JsonResponse(
                {"success": False, "error": "No previous crossing found"}, status=400
            )

        # Calculate mid-point time
        time_delta = crossing.crossing_time - prev_crossing.crossing_time
        mid_time = prev_crossing.crossing_time + (time_delta / 2)
        half_lap_time = time_delta / 2

        # Create first split lap (replace current lap number)
        first_lap = LapCrossing.objects.create(
            race=crossing.race,
            team=crossing.team,
            transponder=crossing.transponder,
            lap_number=crossing.lap_number,
            crossing_time=mid_time,
            lap_time=half_lap_time,
            is_valid=True,
            is_suspicious=False,
            was_split=True,
            split_from=crossing,
            counted_during_suspension=crossing.counted_during_suspension,
            session=crossing.session,
        )

        # Increment all subsequent lap numbers first
        LapCrossing.objects.filter(
            race=crossing.race,
            team=crossing.team,
            lap_number__gt=crossing.lap_number,
        ).update(lap_number=models.F("lap_number") + 1)

        # Create second split lap (at incremented position)
        second_lap = LapCrossing.objects.create(
            race=crossing.race,
            team=crossing.team,
            transponder=crossing.transponder,
            lap_number=crossing.lap_number + 1,
            crossing_time=crossing.crossing_time,
            lap_time=half_lap_time,
            is_valid=True,
            is_suspicious=False,
            was_split=True,
            split_from=crossing,
            counted_during_suspension=crossing.counted_during_suspension,
            session=crossing.session,
        )

        # Mark original as invalid
        crossing.is_valid = False
        crossing.save()

        return JsonResponse(
            {
                "success": True,
                "message": f"Lap {crossing.lap_number} split successfully",
                "first_lap_id": first_lap.id,
                "second_lap_id": second_lap.id,
            }
        )

    except Exception as e:
        return JsonResponse({"success": False, "error": str(e)}, status=400)


@login_required
@user_passes_test(is_admin_user)
@csrf_exempt
@require_POST
def invalidate_lap(request, crossing_id):
    """Mark a lap as invalid"""
    try:
        crossing = get_object_or_404(LapCrossing, id=crossing_id)
        crossing.is_valid = False
        crossing.save()

        return JsonResponse(
            {"success": True, "message": f"Lap {crossing.lap_number} marked as invalid"}
        )

    except Exception as e:
        return JsonResponse({"success": False, "error": str(e)}, status=400)


@login_required
@user_passes_test(is_admin_user)
@csrf_exempt
@require_POST
def validate_lap(request, crossing_id):
    """Mark a lap as valid"""
    try:
        crossing = get_object_or_404(LapCrossing, id=crossing_id)
        crossing.is_valid = True
        crossing.save()

        return JsonResponse(
            {"success": True, "message": f"Lap {crossing.lap_number} marked as valid"}
        )

    except Exception as e:
        return JsonResponse({"success": False, "error": str(e)}, status=400)


# ============================================================
# Race Director Workflow (Phase 7 - Transponder Matching & UI Updates)
# ============================================================


@login_required
@user_passes_test(is_admin_user)
def transponder_matching(request, race_id):
    """Transponder matching interface for race setup"""
    race = get_object_or_404(Race, id=race_id)

    # Get all transponders
    transponders = Transponder.objects.filter(active=True).order_by("transponder_id")

    # Get current assignments
    assignments = RaceTransponderAssignment.objects.filter(race=race).select_related(
        "team", "transponder"
    )

    context = {
        "race": race,
        "transponders": transponders,
        "assignments": assignments,
    }

    return render(request, "pages/transponder_matching.html", context)


@login_required
@user_passes_test(is_admin_user)
def get_transponder_assignments(request, race_id):
    """API endpoint to get current transponder assignments"""
    race = get_object_or_404(Race, id=race_id)

    assignments = RaceTransponderAssignment.objects.filter(race=race).select_related(
        "team__team", "transponder"
    )

    data = []
    for assignment in assignments:
        data.append(
            {
                "id": assignment.id,
                "team_id": assignment.team.id,
                "team_number": assignment.team.number,
                "team_name": assignment.team.name,
                "kart_number": assignment.kart_number,
                "transponder_id": assignment.transponder.transponder_id,
                "confirmed": assignment.confirmed,
            }
        )

    return JsonResponse({"assignments": data})


@login_required
@user_passes_test(is_admin_user)
@csrf_exempt
@require_POST
def assign_transponder(request, race_id):
    """Manually assign a transponder to a team"""
    try:
        data = json.loads(request.body)
        race = get_object_or_404(Race, id=race_id)

        team_id = data.get("team_id")
        transponder_id = data.get("transponder_id")
        kart_number = data.get("kart_number")

        team = get_object_or_404(round_team, id=team_id)
        transponder = get_object_or_404(Transponder, transponder_id=transponder_id)

        # Default kart_number: inherit from existing assignment, else use team number
        if not kart_number:
            existing = RaceTransponderAssignment.objects.filter(
                race=race, team=team
            ).first()
            kart_number = existing.kart_number if existing else team.number

        assignment = RaceTransponderAssignment.objects.create(
            race=race,
            team=team,
            transponder=transponder,
            kart_number=kart_number,
            confirmed=True,
        )

        return JsonResponse(
            {
                "success": True,
                "message": f"Transponder {transponder_id} assigned to Team #{team.team.number}",
                "assignment_id": assignment.id,
            }
        )

    except Exception as e:
        return JsonResponse({"success": False, "error": str(e)}, status=400)


@login_required
@user_passes_test(is_admin_user)
@csrf_exempt
@require_POST
def remove_transponder_assignment(request, assignment_id):
    """Remove a transponder assignment"""
    try:
        assignment = get_object_or_404(RaceTransponderAssignment, id=assignment_id)
        team_number = assignment.team.number
        assignment.delete()

        return JsonResponse(
            {
                "success": True,
                "message": f"Transponder assignment removed from Team #{team_number}",
            }
        )

    except Exception as e:
        return JsonResponse({"success": False, "error": str(e)}, status=400)


@login_required
@user_passes_test(is_admin_or_race_director)
@csrf_exempt
@require_POST
def replace_transponder_assignment(request, assignment_id):
    """Replace the transponder on a single assignment without disturbing the lock state."""
    try:
        assignment = get_object_or_404(RaceTransponderAssignment, id=assignment_id)
        data = json.loads(request.body)
        transponder_id = data.get("transponder_id")
        if not transponder_id:
            return JsonResponse(
                {"success": False, "error": "transponder_id is required"}, status=400
            )

        transponder = get_object_or_404(Transponder, transponder_id=transponder_id)

        old_id = assignment.transponder.transponder_id
        assignment.transponder = transponder
        assignment.save(update_fields=["transponder"])

        return JsonResponse(
            {
                "success": True,
                "message": (
                    f"Transponder replaced for Team #{assignment.team.number}: "
                    f"{old_id} → {transponder_id}"
                ),
            }
        )

    except Exception as e:
        return JsonResponse({"success": False, "error": str(e)}, status=400)


@login_required
@user_passes_test(is_admin_user)
@csrf_exempt
@require_POST
def lock_transponder_assignments(request, race_id):
    """Lock all transponder assignments for the race"""
    try:
        race = get_object_or_404(Race, id=race_id)

        # Check if all teams have at least one assignment
        participating_teams = race.get_all_teams().count()
        assigned_teams = (
            RaceTransponderAssignment.objects.filter(race=race)
            .values("team")
            .distinct()
            .count()
        )

        if assigned_teams < participating_teams:
            return JsonResponse(
                {
                    "success": False,
                    "error": f"Not all teams have transponders assigned ({assigned_teams}/{participating_teams})",
                },
                status=400,
            )

        # Mark all as confirmed and lock the race
        RaceTransponderAssignment.objects.filter(race=race).update(confirmed=True)
        race.grid_locked = True
        race.save(update_fields=["grid_locked"])

        return JsonResponse(
            {
                "success": True,
                "message": f"All {assigned_teams} transponder assignments locked",
            }
        )

    except Exception as e:
        return JsonResponse({"success": False, "error": str(e)}, status=400)


@login_required
@user_passes_test(is_admin_user)
def get_available_transponders(request, race_id):
    """API endpoint to get transponders not yet assigned to this race"""
    race = get_object_or_404(Race, id=race_id)

    # Get assigned transponder IDs
    assigned_transponder_ids = RaceTransponderAssignment.objects.filter(
        race=race
    ).values_list("transponder__transponder_id", flat=True)

    # Get unassigned active transponders
    available = Transponder.objects.filter(active=True).exclude(
        transponder_id__in=assigned_transponder_ids
    )

    data = []
    for transponder in available:
        data.append(
            {
                "transponder_id": transponder.transponder_id,
                "description": transponder.description,
                "last_seen": transponder.last_seen.isoformat()
                if transponder.last_seen
                else None,
            }
        )

    return JsonResponse({"transponders": data})


@login_required
@user_passes_test(is_admin_user)
@csrf_exempt
@require_POST
def retire_team(request):
    """Toggle retired status of a round_team"""
    try:
        data = json.loads(request.body)
        team_id = data.get("team_id")
        if not team_id:
            return JsonResponse(
                {"success": False, "error": "team_id required"}, status=400
            )

        team = get_object_or_404(round_team, id=team_id)
        team.retired = not team.retired
        team.save(update_fields=["retired"])

        return JsonResponse(
            {
                "success": True,
                "team_id": team.id,
                "retired": team.retired,
                "team_name": team.name,
                "team_number": team.number,
            }
        )
    except json.JSONDecodeError:
        return JsonResponse({"success": False, "error": "Invalid JSON"}, status=400)
