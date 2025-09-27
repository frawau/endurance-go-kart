# forms.py
import datetime as dt
from django import forms
from .models import Person, Team, Championship, championship_team
from django.core.exceptions import ValidationError


class DriverForm(forms.ModelForm):
    class Meta:
        model = Person
        fields = [
            "surname",
            "firstname",
            "nickname",
            "gender",
            "birthdate",
            "country",
            "mugshot",
            "email",
        ]
        widgets = {
            "mugshot": forms.FileInput(
                attrs={"class": "file-input", "id": "mugshot-upload"}
            ),
            "birthdate": forms.DateInput(attrs={"type": "date"}),
        }


class TeamForm(forms.ModelForm):
    championship = forms.ModelChoiceField(
        queryset=Championship.objects.none(),  # Will be set in __init__
        required=False,
        empty_label="Select a championship (optional)",
        widget=forms.Select(attrs={"class": "form-control"}),
    )
    team_number = forms.IntegerField(
        required=False,
        min_value=1,
        max_value=99,
        widget=forms.NumberInput(
            attrs={
                "class": "form-control",
                "placeholder": "Enter team number (optional)",
            }
        ),
        help_text="Enter a number between 1 and 99 to register this team in the selected championship.",
    )

    class Meta:
        model = Team
        fields = ["name", "logo"]
        widgets = {
            "logo": forms.FileInput(attrs={"class": "file-input", "id": "logo-upload"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["logo"].required = False

        # Get active championships (where today is between start and end)
        today = dt.date.today()
        self.fields["championship"].queryset = Championship.objects.filter(
            start__lte=today, end__gte=today
        )

    def clean(self):
        cleaned_data = super().clean()
        championship = cleaned_data.get("championship")
        team_number = cleaned_data.get("team_number")

        # If one is provided, both must be provided
        if bool(championship) != bool(team_number):
            if championship and not team_number:
                raise ValidationError(
                    "You must provide a team number if you select a championship."
                )
            if team_number and not championship:
                raise ValidationError(
                    "You must select a championship if you provide a team number."
                )

        # Check if the number is already taken in this championship
        if championship and team_number:
            existing = championship_team.objects.filter(
                championship=championship, number=team_number
            ).exists()

            if existing:
                raise ValidationError(
                    f"Team number {team_number} is already taken in this championship."
                )

        return cleaned_data


class JoinChampionshipForm(forms.Form):
    championship = forms.ModelChoiceField(
        queryset=Championship.objects.none(),
        required=True,
        empty_label="Select a championship",
        widget=forms.Select(
            attrs={"class": "form-control", "id": "championship-select"}
        ),
    )
    team = forms.IntegerField(
        required=True,
        widget=forms.Select(attrs={"class": "form-control", "id": "team-select"}),
    )
    number = forms.IntegerField(
        required=True,
        min_value=1,
        max_value=99,
        widget=forms.Select(attrs={"class": "form-control", "id": "number-select"}),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Get active championships
        today = dt.date.today()
        active_championships = Championship.objects.filter(
            start__lte=today, end__gte=today
        )
        self.fields["championship"].queryset = active_championships
