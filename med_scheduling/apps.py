from django.apps import AppConfig
from django.utils.translation import gettext_lazy


class MedSchedulingConfig(AppConfig):
    name = __package__
    label = "med_scheduling"
    verbose_name = gettext_lazy("Agenda médica")
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self) -> None:
        from pathlib import Path

        from skeleton.system.app_registry import AppManifest, register_app

        register_app(AppManifest.from_json(Path(self.path) / "manifest.json", app_config=self))
        from . import registration

        registration.register_practice_tables()
        registration.register_schedule_tables()
        registration.register_appointments()
        registration.register_notifications()
