from django.apps import AppConfig


class MedPatientsConfig(AppConfig):
    name = __package__
    label = "med_patients"
    verbose_name = "Pacientes"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self):
        from pathlib import Path

        from skeleton.system.app_registry import AppManifest, register_app
        from skeleton.system.registry import TableSpec, register

        register_app(AppManifest.from_json(Path(self.path) / "manifest.json", app_config=self))
        from .models import PatientRegistry

        register(
            TableSpec(
                model=PatientRegistry,
                description="Registros de PatientRegistry da app med_patients",
                label="PatientRegistry",
                scope="organization",
                read_fields=("code", "title", "owner", "visibility", "owning_group"),
                write_fields=("code", "title"),
                # Liste aqui todo campo cujo valor não pode aparecer na auditoria.
                sensitive_fields=(),
                expose_api=True,
            )
        )
