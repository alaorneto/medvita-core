"""Forms of the records pages: format checks only; the rules live in RecordsService.

The section form is built on the server from the ``SectionField`` list of the section type, so
no page edits JSON by hand.
"""

from __future__ import annotations

from typing import Any

from django import forms
from django.utils.translation import gettext
from django.utils.translation import gettext_lazy as _

from .models import Allergy, Archive, Encounter, Medication


def _date():
    return forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d")


def apply_service_errors(form: forms.Form, error: Any) -> None:
    """Show an InvalidInput of the service on the form, by field when the form has it."""
    for name, messages in error.errors.items():
        target = name.removeprefix("data.")
        field = target if target in form.fields else None
        for message in messages:
            form.add_error(field, message)


class SetupForm(forms.Form):
    mode = forms.ChoiceField(
        label=_("Organização do prontuário"),
        choices=(
            ("shared", _("Um prontuário da clínica, compartilhado pelos grupos escolhidos")),
            ("per_professional", _("Um prontuário por profissional, que só ele lê")),
        ),
    )
    name = forms.CharField(label=_("Nome do arquivo (prontuário da clínica)"), max_length=120, required=False)
    member_groups = forms.MultipleChoiceField(
        label=_("Grupos que leem e escrevem (prontuário da clínica)"),
        required=False,
        widget=forms.CheckboxSelectMultiple,
    )

    def __init__(self, *args, groups=(), **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["member_groups"].choices = [(str(group.sysid), group.name) for group in groups]


class NewEncounterForm(forms.Form):
    kind = forms.ChoiceField(
        label=_("Tipo"), choices=[(code, label) for code, label in Encounter.Kind.choices if code != "addendum"]
    )
    template = forms.ChoiceField(label=_("Modelo"), required=False)

    def __init__(self, *args, templates=(), **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["template"].choices = [("", "—"), *((str(item.sysid), item.name) for item in templates)]


def _field(field: Any) -> forms.Field:
    label = field.label if not field.unit else f"{field.label} ({field.unit})"
    if field.kind == "text":
        return forms.CharField(label=label, max_length=500, required=False)
    if field.kind == "long_text":
        return forms.CharField(label=label, required=False, widget=forms.Textarea(attrs={"rows": 3}))
    if field.kind == "integer":
        return forms.IntegerField(label=label, required=False, min_value=field.min, max_value=field.max)
    if field.kind == "decimal":
        return forms.CharField(
            label=label,
            required=False,
            max_length=20,
            widget=forms.TextInput(attrs={"inputmode": "decimal", "autocomplete": "off"}),
        )
    if field.kind == "boolean":
        return forms.BooleanField(label=label, required=False)
    if field.kind == "choice":
        return forms.ChoiceField(label=label, required=False, choices=[("", "—"), *field.choices])
    if field.kind == "date":
        return forms.DateField(label=label, required=False, widget=_date())
    return forms.CharField(
        label=label,
        required=False,
        widget=forms.Textarea(attrs={"rows": 3}),
        help_text=_("Um diagnóstico por linha: código CID-10 e descrição (ex.: J45.0 Asma). O primeiro é o principal."),
    )


def section_form(section_type: Any, *args: Any, **kwargs: Any) -> forms.Form:
    """A form with one field per structured field of the section type, plus the free text."""
    fields: dict[str, forms.Field] = {field.name: _field(field) for field in section_type.fields}
    if section_type.has_text:
        fields["text"] = forms.CharField(
            label=gettext("Texto"), required=False, widget=forms.Textarea(attrs={"rows": 5})
        )
    form_class = type("SectionForm", (forms.Form,), fields)
    return form_class(*args, **kwargs)


def section_initial(section_type: Any, data: dict[str, Any], text: str) -> dict[str, Any]:
    initial = dict(data)
    for field in section_type.fields:
        if field.kind == "icd10_list" and isinstance(data.get(field.name), list):
            initial[field.name] = "\n".join(
                f"{item.get('code', '')} {item.get('description', '')}".strip() for item in data[field.name]
            )
    initial["text"] = text
    return initial


def section_data(section_type: Any, cleaned: dict[str, Any]) -> tuple[tuple[str, Any], ...]:
    """The ``(field, value)`` pairs RecordsService.save_section takes."""
    pairs = []
    for field in section_type.fields:
        value = cleaned.get(field.name)
        if field.kind == "icd10_list":
            items = []
            for number, line in enumerate((value or "").splitlines()):
                parts = line.strip().split(None, 1)
                if parts:
                    items.append(
                        {"code": parts[0], "description": parts[1] if len(parts) > 1 else "", "primary": number == 0}
                    )
            value = items
        elif field.kind == "date" and value is not None:
            value = value.isoformat()
        elif field.kind == "boolean":
            value = bool(value)
        if value in (None, "", []) or (field.kind == "boolean" and value is False):
            continue
        pairs.append((field.name, value))
    return tuple(pairs)


class AddendumForm(forms.Form):
    text = forms.CharField(label=_("Texto do adendo"), widget=forms.Textarea(attrs={"rows": 4}))


class AllergyForm(forms.Form):
    substance = forms.CharField(label=_("Substância"), max_length=200)
    category = forms.ChoiceField(label=_("Categoria"), choices=Allergy.Category.choices)
    reaction = forms.CharField(label=_("Reação"), max_length=300, required=False)
    severity = forms.ChoiceField(label=_("Gravidade"), choices=Allergy.Severity.choices)
    noted_on = forms.DateField(label=_("Desde"), required=False, widget=_date())


class MedicationForm(forms.Form):
    name = forms.CharField(label=_("Medicamento"), max_length=200)
    dose = forms.CharField(label=_("Dose"), max_length=80, required=False)
    route = forms.CharField(label=_("Via"), max_length=40, required=False)
    frequency = forms.CharField(label=_("Posologia"), max_length=120, required=False)
    started_on = forms.DateField(label=_("Início"), required=False, widget=_date())
    note = forms.CharField(label=_("Observação"), max_length=300, required=False)


class StatusForm(forms.Form):
    status = forms.CharField(max_length=10)


class NewDocumentForm(forms.Form):
    kind = forms.ChoiceField(label=_("Tipo de documento"))
    template = forms.ChoiceField(label=_("Modelo"), required=False)

    def __init__(self, *args, kinds=(), templates=(), **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["kind"].choices = [(item.code, str(item.label)) for item in kinds]
        self.fields["template"].choices = [("", "—"), *((str(item.sysid), item.name) for item in templates)]


class DocumentForm(forms.Form):
    title = forms.CharField(label=_("Título"), max_length=200)
    body = forms.CharField(label=_("Texto"), widget=forms.Textarea(attrs={"rows": 12}), required=False)


class TemplateForm(forms.Form):
    name = forms.CharField(label=_("Nome"), max_length=120)
    specialty = forms.CharField(label=_("Especialidade"), max_length=80, required=False)
    document_kind = forms.ChoiceField(label=_("Tipo de documento"))
    body = forms.CharField(
        label=_("Texto"),
        widget=forms.Textarea(attrs={"rows": 6}),
        help_text=_("Marcadores: {{patient_name}}, {{date}}, {{professional_name}}."),
    )
    personal = forms.BooleanField(label=_("Só para mim"), required=False)

    def __init__(self, *args, kinds=(), **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["document_kind"].choices = [(item.code, str(item.label)) for item in kinds]


ARCHIVE_KINDS = Archive.Kind
MEDICATION_STATUSES = Medication.Status
