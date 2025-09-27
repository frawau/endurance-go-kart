# race/scheduler.py
from apscheduler.schedulers.background import BackgroundScheduler
from django_apscheduler.jobstores import DjangoJobStore
from django.db import connection
from django_apscheduler.models import DjangoJobExecution


def delete_old_job_executions():
    """Deletes job execution logs older than 24 hours"""
    DjangoJobExecution.objects.delete_old_job_executions(24 * 60 * 60)


def racing_start():
    # Close any existing connections first
    connection.close()

    # Create scheduler
    scheduler = BackgroundScheduler()

    # Import the standalone function
    from race.tasks import run_race_events

    # Add job using the function reference (must be at module level)
    scheduler.add_job(
        run_race_events,
        "interval",
        minutes=1,
        id="race-event-task",
        replace_existing=True,
    )

    # Run cleanup every hour
    scheduler.add_job(
        delete_old_job_executions,
        trigger="interval",
        hours=1,
        id="delete_old_job_executions",
        replace_existing=True,
    )
    # Only add the jobstore after defining jobs to avoid initialization DB access
    scheduler.add_jobstore(DjangoJobStore(), "default")

    # Start the scheduler
    scheduler.start()
