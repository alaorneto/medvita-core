from django.apps import AppConfig


class MedRecordsConfig(AppConfig):
    name = __package__
    label = "med_records"
    verbose_name = "Prontuário"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self):
        from pathlib import Path

        from skeleton.system.app_registry import AppManifest, register_app
        from skeleton.system.registry import TableSpec, register

        register_app(AppManifest.from_json(Path(self.path) / "manifest.json", app_config=self))
        from .models import Archive

        register(
            TableSpec(
                model=Archive,
                description="Registros de Archive da app med_records",
                label="Archive",
                scope="organization",
                read_fields=("code", "title", "owner", "visibility", "owning_group"),
                write_fields=("code", "title"),
                # Liste aqui todo campo cujo valor não pode aparecer na auditoria.
                sensitive_fields=(),
                expose_api=True,
            )
        )
