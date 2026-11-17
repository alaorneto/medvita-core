from django.apps import AppConfig
from django.utils.translation import gettext_lazy


class MedPatientsConfig(AppConfig):
    name = __package__
    label = "med_patients"
    verbose_name = gettext_lazy("Pacientes")
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self) -> None:
        from pathlib import Path

        from skeleton.system.app_registry import AppManifest, register_app

        register_app(AppManifest.from_json(Path(self.path) / "manifest.json", app_config=self))
        from .registration import register_tables

        register_tables()
        from .registration import register_sequences_and_events

        register_sequences_and_events()
        from .registration import register_patient_rows

        register_patient_rows()
        from .registration import register_consents

        register_consents()
