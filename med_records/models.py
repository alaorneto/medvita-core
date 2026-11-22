"""Tables of the records app (docs/spec.md, "Modelo de dados").

One container decides access: ``Archive`` (a clinical archive, of the whole clinic or of one
professional). Every other table is derived from it (``TableSpec.access_parent``), directly or
through the patient's chart. Clinical content is in ``sensitive_fields``.
"""

from __future__ import annotations

from django.db import models
from django.db.models import Q
from django.utils.translation import gettext_lazy

from skeleton.common.models import OrganizationRecord, SealableMixin, SecuredRecord, SystemRecord


class Archive(SecuredRecord):
    """A clinical archive: the unit of confidentiality (who reads it reads its charts)."""

    class Kind(models.TextChoices):
        SHARED = "shared", gettext_lazy("Da clínica")
        PERSONAL = "personal", gettext_lazy("De um profissional")

    name = models.CharField(max_length=120)
    kind = models.CharField(max_length=10, choices=Kind.choices, default=Kind.SHARED)
    is_default = models.BooleanField(default=False)
    immutable_fields = ("kind",)

    class Meta(SecuredRecord.Meta):
        constraints = SecuredRecord.Meta.constraints + [
            models.UniqueConstraint(
                fields=("organization",),
                condition=Q(is_default=True, deleted_at__isnull=True),
                name="med_records_one_default_archive",
                violation_error_code="unique",
            ),
        ]
        ordering = ("-is_default", "name", "sysid")

    def __str__(self) -> str:
        return self.name


class PatientChart(OrganizationRecord):
    """The chart of one patient in one archive."""

    archive = models.ForeignKey(Archive, on_delete=models.PROTECT, related_name="+")
    patient = models.ForeignKey("med_patients.Patient", on_delete=models.PROTECT, related_name="med_records_charts")
    opened_at = models.DateTimeField()
    last_entry_at = models.DateTimeField(null=True, blank=True)
    immutable_fields = ("archive_id", "patient_id", "opened_at")

    class Meta(OrganizationRecord.Meta):
        constraints = OrganizationRecord.Meta.constraints + [
            models.UniqueConstraint(
                fields=("archive", "patient"),
                condition=Q(deleted_at__isnull=True),
                name="med_records_one_chart_per_archive",
                violation_error_code="unique",
            ),
        ]
        indexes = [models.Index(fields=("organization", "patient"), name="med_records_chart_patient")]
        ordering = ("opened_at", "sysid")


class Encounter(SealableMixin, OrganizationRecord):
    """One encounter of the chart: a draft only its author changes, sealed when signed.

    A signed encounter never changes; a correction is an addendum (``kind="addendum"``) pointing
    to the original with ``amends``.
    """

    class Kind(models.TextChoices):
        CONSULTATION = "consultation", gettext_lazy("Consulta")
        RETURN = "return", gettext_lazy("Retorno")
        PROCEDURE = "procedure", gettext_lazy("Procedimento")
        REMOTE_CONTACT = "remote_contact", gettext_lazy("Contato a distância")
        NOTE = "note", gettext_lazy("Anotação")
        ADDENDUM = "addendum", gettext_lazy("Adendo")

    chart = models.ForeignKey(PatientChart, on_delete=models.PROTECT, related_name="+")
    patient = models.ForeignKey("med_patients.Patient", on_delete=models.PROTECT, related_name="+")
    code = models.CharField(max_length=20)
    kind = models.CharField(max_length=16, choices=Kind.choices, default=Kind.CONSULTATION)
    occurred_at = models.DateTimeField()
    author = models.ForeignKey("sk_accounts.User", on_delete=models.PROTECT, related_name="+")
    author_name = models.CharField(max_length=200, blank=True)
    author_council = models.CharField(max_length=60, blank=True)
    appointment = models.ForeignKey(
        "med_scheduling.Appointment", on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    amends = models.ForeignKey("self", on_delete=models.PROTECT, null=True, blank=True, related_name="+")
    # The references are immutable from creation (immutable_fields); the seal digest covers them
    # through ``seal_extra`` and the seal freezes the columns a draft may still change.
    seal_fields = ("code", "kind", "occurred_at", "author_name", "author_council")
    immutable_fields = ("chart_id", "patient_id", "author_id", "appointment_id", "amends_id")

    class Meta(OrganizationRecord.Meta):
        constraints = OrganizationRecord.Meta.constraints + [
            models.UniqueConstraint(fields=("organization", "code"), name="med_records_encounter_code"),
            models.CheckConstraint(
                condition=Q(kind="addendum", amends__isnull=False) | (~Q(kind="addendum") & Q(amends__isnull=True)),
                name="med_records_addendum_amends",
            ),
        ]
        indexes = [models.Index(fields=("chart", "occurred_at"), name="med_records_encounter_chart")]
        ordering = ("-occurred_at", "sysid")


class EncounterSection(OrganizationRecord):
    """A structured section of an encounter; frozen with the encounter's seal."""

    encounter = models.ForeignKey(Encounter, on_delete=models.PROTECT, related_name="+")
    section_type = models.CharField(max_length=80)
    type_version = models.PositiveSmallIntegerField(default=1)
    position = models.PositiveSmallIntegerField(default=0)
    data = models.JSONField(default=dict, blank=True)
    text = models.TextField(blank=True)
    seal_parent = "encounter"
    immutable_fields = ("encounter_id", "section_type")

    class Meta(OrganizationRecord.Meta):
        constraints = OrganizationRecord.Meta.constraints + [
            models.UniqueConstraint(
                fields=("encounter", "section_type", "position"),
                condition=Q(deleted_at__isnull=True),
                name="med_records_one_section_per_slot",
                violation_error_code="unique",
            ),
        ]
        ordering = ("position", "section_type", "sysid")


class Allergy(OrganizationRecord):
    """An allergy or intolerance of the patient, on the chart."""

    class Category(models.TextChoices):
        DRUG = "drug", gettext_lazy("Medicamento")
        FOOD = "food", gettext_lazy("Alimento")
        ENVIRONMENT = "environment", gettext_lazy("Ambiental")
        OTHER = "other", gettext_lazy("Outra")

    class Severity(models.TextChoices):
        MILD = "mild", gettext_lazy("Leve")
        MODERATE = "moderate", gettext_lazy("Moderada")
        SEVERE = "severe", gettext_lazy("Grave")
        UNKNOWN = "unknown", gettext_lazy("Não informada")

    class Status(models.TextChoices):
        ACTIVE = "active", gettext_lazy("Ativa")
        RESOLVED = "resolved", gettext_lazy("Resolvida")
        REFUTED = "refuted", gettext_lazy("Descartada")

    chart = models.ForeignKey(PatientChart, on_delete=models.PROTECT, related_name="+")
    substance = models.CharField(max_length=200)
    category = models.CharField(max_length=12, choices=Category.choices, default=Category.OTHER)
    reaction = models.CharField(max_length=300, blank=True)
    severity = models.CharField(max_length=10, choices=Severity.choices, default=Severity.UNKNOWN)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.ACTIVE)
    noted_on = models.DateField(null=True, blank=True)
    immutable_fields = ("chart_id",)

    class Meta(OrganizationRecord.Meta):
        ordering = ("substance", "sysid")


class Medication(OrganizationRecord):
    """A medication the patient uses, on the chart."""

    class Status(models.TextChoices):
        ACTIVE = "active", gettext_lazy("Em uso")
        SUSPENDED = "suspended", gettext_lazy("Suspenso")
        ENDED = "ended", gettext_lazy("Encerrado")

    chart = models.ForeignKey(PatientChart, on_delete=models.PROTECT, related_name="+")
    name = models.CharField(max_length=200)
    dose = models.CharField(max_length=80, blank=True)
    route = models.CharField(max_length=40, blank=True)
    frequency = models.CharField(max_length=120, blank=True)
    started_on = models.DateField(null=True, blank=True)
    ended_on = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.ACTIVE)
    note = models.CharField(max_length=300, blank=True)
    immutable_fields = ("chart_id",)

    class Meta(OrganizationRecord.Meta):
        constraints = OrganizationRecord.Meta.constraints + [
            models.CheckConstraint(
                condition=Q(ended_on__isnull=True)
                | Q(started_on__isnull=True)
                | Q(ended_on__gte=models.F("started_on")),
                name="med_records_medication_dates",
            ),
        ]
        ordering = ("name", "sysid")


class Icd10Code(SystemRecord):
    """The ICD-10 reference table, global to the platform and written only by ``load_icd10``.

    The repository does not ship the table: the operator loads the official one (DATASUS).
    """

    code = models.CharField(max_length=8, unique=True)
    description = models.CharField(max_length=300)
    is_category = models.BooleanField(default=False)
    search_text = models.CharField(max_length=320, db_index=True)

    class Meta(SystemRecord.Meta):
        ordering = ("code",)


class EntryTemplate(OrganizationRecord):
    """A template of encounter sections or of a document; with ``author`` it is personal to that person."""

    class Kind(models.TextChoices):
        ENCOUNTER = "encounter", gettext_lazy("Atendimento")
        DOCUMENT = "document", gettext_lazy("Documento")

    archive = models.ForeignKey(Archive, on_delete=models.PROTECT, related_name="+")
    name = models.CharField(max_length=120)
    specialty = models.CharField(max_length=80, blank=True)
    kind = models.CharField(max_length=10, choices=Kind.choices)
    sections = models.JSONField(default=list, blank=True)
    document_kind = models.CharField(max_length=80, blank=True)
    body = models.TextField(blank=True)
    author = models.ForeignKey("sk_accounts.User", on_delete=models.PROTECT, null=True, blank=True, related_name="+")
    is_active = models.BooleanField(default=True)
    immutable_fields = ("archive_id", "kind", "author_id")

    class Meta(OrganizationRecord.Meta):
        ordering = ("name", "sysid")


class ClinicalDocument(SealableMixin, OrganizationRecord):
    """A simple clinical document (certificate, prescription, request): a draft until issued, then sealed.

    An issued document never changes; a correction is a new document that ``replaces`` it.
    """

    chart = models.ForeignKey(PatientChart, on_delete=models.PROTECT, related_name="+")
    patient = models.ForeignKey("med_patients.Patient", on_delete=models.PROTECT, related_name="+")
    code = models.CharField(max_length=20)
    kind = models.CharField(max_length=80)
    title = models.CharField(max_length=200)
    body = models.TextField(blank=True)
    issued_at = models.DateTimeField(null=True, blank=True)
    author = models.ForeignKey("sk_accounts.User", on_delete=models.PROTECT, related_name="+")
    author_name = models.CharField(max_length=200, blank=True)
    author_council = models.CharField(max_length=60, blank=True)
    encounter = models.ForeignKey(Encounter, on_delete=models.PROTECT, null=True, blank=True, related_name="+")
    replaces = models.ForeignKey("self", on_delete=models.PROTECT, null=True, blank=True, related_name="+")
    # The references are immutable from creation; the seal digest covers them through the extra.
    seal_fields = ("code", "kind", "title", "body", "issued_at", "author_name", "author_council")
    immutable_fields = ("chart_id", "patient_id", "author_id", "encounter_id", "replaces_id")

    class Meta(OrganizationRecord.Meta):
        constraints = OrganizationRecord.Meta.constraints + [
            models.UniqueConstraint(fields=("organization", "code"), name="med_records_document_code"),
        ]
        indexes = [models.Index(fields=("chart", "created_at"), name="med_records_document_chart")]
        ordering = ("-created_at", "sysid")


class AccessLog(OrganizationRecord):
    """One read of clinical content of a chart (the core audit covers writes only). Never changes."""

    class Action(models.TextChoices):
        VIEW_CHART = "view_chart", gettext_lazy("Leitura do prontuário")
        VIEW_ENCOUNTER = "view_encounter", gettext_lazy("Leitura de atendimento")
        VIEW_DOCUMENT = "view_document", gettext_lazy("Leitura de documento")
        PRINT_DOCUMENT = "print_document", gettext_lazy("Impressão de documento")
        DOWNLOAD_ATTACHMENT = "download_attachment", gettext_lazy("Download de anexo")
        EXPORT = "export", gettext_lazy("Exportação")

    class Origin(models.TextChoices):
        """Where the read came from, by the credential of the request (#61)."""

        WEB = "web", gettext_lazy("Sessão web")
        NATIVE_CLIENT = "native_client", gettext_lazy("Cliente nativo")
        API_TOKEN = "api_token", gettext_lazy("Token de API")
        OTHER = "other", gettext_lazy("Outra")

    chart = models.ForeignKey(PatientChart, on_delete=models.PROTECT, related_name="+")
    actor = models.ForeignKey("sk_accounts.User", on_delete=models.PROTECT, related_name="+")
    action = models.CharField(max_length=20, choices=Action.choices)
    target_table = models.CharField(max_length=60, blank=True)
    target_id = models.UUIDField(null=True, blank=True)
    at = models.DateTimeField()
    # Every read before #61 came from a web session: tokens were refused by every view of the app.
    origin = models.CharField(max_length=20, choices=Origin.choices, default=Origin.WEB)
    # The OIDC client of a native client read (2 to 64 characters, never a secret); empty otherwise.
    client_id = models.CharField(max_length=64, blank=True)
    immutable_fields = ("chart_id", "actor_id", "action", "target_table", "target_id", "at", "origin", "client_id")

    class Meta(OrganizationRecord.Meta):
        indexes = [models.Index(fields=("chart", "at"), name="med_records_access_chart")]
        ordering = ("-at", "sysid")
