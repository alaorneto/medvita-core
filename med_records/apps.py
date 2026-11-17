from django.apps import AppConfig
from django.utils.translation import gettext_lazy


class MedRecordsConfig(AppConfig):
    name = __package__
    label = "med_records"
    verbose_name = gettext_lazy("Prontuário")
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self) -> None:
        from pathlib import Path

        from skeleton.system.app_registry import AppManifest, register_app

        register_app(AppManifest.from_json(Path(self.path) / "manifest.json", app_config=self))
        from . import registration

        registration.register_archive_tables()
        registration.register_contributions()
        registration.register_clinical_types()
        registration.register_encounters()
        registration.register_clinical_lists()
        registration.register_icd10()
        registration.register_documents()
