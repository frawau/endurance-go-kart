from django.apps import AppConfig
import threading


class RaceConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "race"

    def ready(self):
        import race.signals

        # Only run in main thread and not in reloader thread
        if threading.current_thread() == threading.main_thread():
            # Use a slightly delayed start to avoid DB access during initialization
            def delayed_start():
                import time

                time.sleep(5)  # Wait 5 seconds for Django to fully initialize
                from race.scheduler import racing_start

                racing_start()

            t = threading.Thread(target=delayed_start)
            t.daemon = True
            t.start()
