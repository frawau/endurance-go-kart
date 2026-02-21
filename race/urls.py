# -*- encoding: utf-8 -*-
"""
Copyright (c) 2019 - present AppSeed.us
"""

from django.urls import path
from . import consumers
from . import views
from .pdfcardview import GenerateCardPDF
from .teammgt import TeamMembersView, TeamManagementSelectionView

urlpatterns = [
    path("", views.index, name="Home"),
    path("teamcarousel/", views.team_carousel, name="Participating Teams"),
    path(
        "teamcarousel-nav/",
        views.team_carousel_with_nav,
        name="Participating Teams with Navigation",
    ),
    path("racecontrol/", views.racecontrol, name="Race Control"),
    path("get_team_card/", views.get_team_card, name="Team Card"),
    # path('ws/pitlane/<int:lane_number>/', views.changelane_info, name = 'change_lane_ws'),
    path("pitlane/<int:lane_number>/", views.changelane_info, name="Change Lane"),
    path("all_pitlanes/", views.all_pitlanes, name="All Pit Lanes"),
    path(
        "pitlanedetail/<int:lane_number>/",
        views.changelane_detail,
        name="Change Lane Info",
    ),
    path(
        "pitlanevdetail/<int:lane_number>/",
        views.changelane_vdetail,
        name="Change Lane Large Info",
    ),
    path("changedriver/", views.changedriver_info, name="Call for Driver Change"),
    path("preracecheck/", views.preracecheck, name="preracecheck"),
    path("race/start/", views.race_start, name="race_start"),
    path("falsestart/", views.falsestart, name="falsestart"),
    path("racepaused/", views.racepaused, name="racepaused"),
    path("racerestart/", views.racerestart, name="racerestart"),
    path("falserestart/", views.falserestart, name="falserestart"),
    path("endofrace/", views.endofrace, name="endofrace"),
    path("generate_card/", GenerateCardPDF.as_view(), name="generate_cards"),
    path("agent_login/", views.agent_login, name="Agent Login"),
    path("driver_queue/", views.add_driver_to_queue, name="Driver Queue"),
    path("driver_change/", views.change_kart_driver, name="Driver Change"),
    path("pending_drivers/", views.pending_drivers, name="pending_drivers"),
    path(
        "pending_drivers-nav/",
        views.pending_drivers_with_nav,
        name="pending_drivers with Navigation",
    ),
    path(
        "api/driver/<int:driver_id>/info/",
        views.driver_info_api,
        name="driver_info_api",
    ),
    path("round_info/", views.round_info, name="round_info"),
    path("round_penalties/", views.round_penalties, name="round_penalties"),
    # Admin stuffs
    path("rounds/update/", views.round_list_update, name="rounds_list"),
    path("rounds/form/", views.round_form, name="round_form"),
    path("rounds/update/<int:round_id>/", views.update_round, name="update_round"),
    path("rounds/team/", TeamMembersView.as_view(), name="team_members"),
    path(
        "rounds/team/select/",
        TeamManagementSelectionView.as_view(),
        name="team_management_selection",
    ),
    path(
        "rounds/team/<int:round_id>/",
        TeamMembersView.as_view(),
        name="team_members_by_id",
    ),
    path("driver/add/", views.create_driver, name="add_driver"),
    path("team/add/", views.create_team, name="add_team"),
    path("get_round_status/", views.get_round_status, name="get_round_status"),
    path("get_race_lanes/", views.get_race_lanes, name="get_race_lane"),
    path("singleteam/", views.singleteam_view, name="single_team"),
    path("join_championship/", views.join_championship_view, name="join_championship"),
    path("api/get_teams/", views.get_available_teams, name="get_available_teams"),
    path("api/get_numbers/", views.get_available_numbers, name="get_available_numbers"),
    path("alldrivers/", views.all_drivers_view, name="all_drivers"),
    path("allteams/", views.all_teams_view, name="all_teams"),
    path("edit/driver/", views.edit_driver_view, name="edit_driver"),
    path("edit/team/", views.edit_team_view, name="edit_team"),
    path(
        "championship/create/",
        views.create_championship_view,
        name="create_championship",
    ),
    path("championship/edit/", views.edit_championship_view, name="edit_championship"),
    path("championship/edit-round/", views.edit_round_view, name="edit_round"),
    path(
        "api/championship/<int:championship_id>/rounds/",
        views.get_championship_rounds,
        name="get_championship_rounds",
    ),
    path(
        "transponder/manage/",
        views.transponder_management_view,
        name="transponder_management",
    ),
    path("penalty/manage/", views.penalty_management_view, name="penalty_management"),
    path("sponsor/manage/", views.sponsor_management_view, name="sponsor_management"),
    path(
        "api/championship/<int:championship_id>/available-penalties/",
        views.get_available_penalties,
        name="get_available_penalties",
    ),
    path(
        "api/championship/<int:championship_id>/penalties/",
        views.get_championship_penalties,
        name="get_championship_penalties",
    ),
    path(
        "api/round/<int:round_id>/stop-go-penalties/",
        views.get_stop_and_go_penalties,
        name="get_stop_and_go_penalties",
    ),
    path(
        "api/create-round-penalty/",
        views.create_round_penalty,
        name="create_round_penalty",
    ),
    path(
        "api/update-penalty-served/",
        views.update_penalty_served,
        name="update_penalty_served",
    ),
    path(
        "api/round/<int:round_id>/laps-penalties/",
        views.get_laps_penalties,
        name="get_laps_penalties",
    ),
    # Penalty Queue API endpoints
    path(
        "api/queue-penalty/",
        views.queue_penalty,
        name="queue_penalty",
    ),
    path(
        "api/round/<int:round_id>/penalty-queue-status/",
        views.get_penalty_queue_status,
        name="get_penalty_queue_status",
    ),
    path(
        "api/serve-penalty/",
        views.serve_penalty,
        name="serve_penalty",
    ),
    path(
        "api/cancel-penalty/",
        views.cancel_penalty,
        name="cancel_penalty",
    ),
    path(
        "api/delay-penalty/",
        views.delay_penalty,
        name="delay_penalty",
    ),
    # Grid Management (Phase 4 - Qualifying & Grid System)
    path(
        "race/<int:race_id>/grid/",
        views.race_grid_management,
        name="race_grid_management",
    ),
    path(
        "api/race/<int:race_id>/grid/update/",
        views.update_grid_position,
        name="update_grid_position",
    ),
    path(
        "api/race/<int:race_id>/grid/reorder/",
        views.reorder_grid_positions,
        name="reorder_grid_positions",
    ),
    path(
        "race/<int:race_id>/grid/lock/",
        views.lock_grid,
        name="lock_grid",
    ),
    path(
        "race/<int:race_id>/grid/unlock/",
        views.unlock_grid,
        name="unlock_grid",
    ),
    path(
        "race/<int:race_id>/grid/reset/",
        views.reset_grid_to_auto,
        name="reset_grid_to_auto",
    ),
    path(
        "race/<int:race_id>/grid/auto-assign-qualifying/",
        views.auto_assign_from_qualifying,
        name="auto_assign_from_qualifying",
    ),
    path(
        "race/<int:race_id>/grid/auto-assign-championship/",
        views.auto_assign_from_championship,
        name="auto_assign_from_championship",
    ),
    # Leaderboard (Phase 5 - Leaderboard & Displays)
    path(
        "leaderboard/<int:race_id>/",
        views.public_leaderboard,
        name="public_leaderboard",
    ),
    # Lap Management (Phase 6 - Lap Splitting & Suspicious Lap Detection)
    path(
        "race/<int:race_id>/laps/",
        views.race_lap_management,
        name="race_lap_management",
    ),
    path(
        "api/race/<int:race_id>/laps/",
        views.get_race_laps,
        name="get_race_laps",
    ),
    path(
        "api/lap/<int:crossing_id>/split/",
        views.split_lap,
        name="split_lap",
    ),
    path(
        "api/lap/<int:crossing_id>/invalidate/",
        views.invalidate_lap,
        name="invalidate_lap",
    ),
    path(
        "api/lap/<int:crossing_id>/validate/",
        views.validate_lap,
        name="validate_lap",
    ),
    # Transponder Matching (Phase 7 - Race Director Workflow)
    path(
        "race/<int:race_id>/transponders/",
        views.transponder_matching,
        name="transponder_matching",
    ),
    path(
        "api/race/<int:race_id>/transponder-assignments/",
        views.get_transponder_assignments,
        name="get_transponder_assignments",
    ),
    path(
        "api/race/<int:race_id>/assign-transponder/",
        views.assign_transponder,
        name="assign_transponder",
    ),
    path(
        "api/transponder-assignment/<int:assignment_id>/remove/",
        views.remove_transponder_assignment,
        name="remove_transponder_assignment",
    ),
    path(
        "api/transponder-assignment/<int:assignment_id>/replace/",
        views.replace_transponder_assignment,
        name="replace_transponder_assignment",
    ),
    path(
        "api/race/<int:race_id>/lock-transponder-assignments/",
        views.lock_transponder_assignments,
        name="lock_transponder_assignments",
    ),
    path(
        "api/race/<int:race_id>/available-transponders/",
        views.get_available_transponders,
        name="get_available_transponders",
    ),
    # Team Retirement
    path(
        "api/retire-team/",
        views.retire_team,
        name="retire_team",
    ),
]
