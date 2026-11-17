from django.apps import AppConfig
from django.utils.translation import gettext_lazy


class MedFinanceConfig(AppConfig):
    name = __package__
    label = "med_finance"
    verbose_name = gettext_lazy("Financeiro")
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self) -> None:
        from pathlib import Path

        from skeleton.system.app_registry import AppManifest, register_app

        register_app(AppManifest.from_json(Path(self.path) / "manifest.json", app_config=self))
        from . import registration

        registration.register_price_and_desk_tables()
        registration.register_account_keys()
        registration.register_cash_tables()
        registration.register_charges()
        registration.register_contributions()
