"""Forms of the patients pages: format only. The rules live in PatientService."""

from __future__ import annotations

from django import forms
from django.utils.translation import gettext_lazy as _

from .models import Consent, Patient, PatientGuardian
from .validators import STATES


def _date_input() -> forms.DateInput:
    return forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d")


# Personal data never goes to the browser's form history: the reception computer is shared (#120).
NUMERIC = {"inputmode": "numeric", "autocomplete": "off", "spellcheck": "false"}
PHONE = {"type": "tel", "inputmode": "tel", "autocomplete": "off"}
EMAIL = {"autocomplete": "off", "spellcheck": "false"}


def keep_private(form: forms.Form, **attrs: dict[str, str]) -> None:
    """Every field of a personal-data form without browser history; the named ones get their keyboard."""
    for name, field in form.fields.items():
        field.widget.attrs.setdefault("autocomplete", "off")
        field.widget.attrs.update(attrs.get(name, {}))


class PatientForm(forms.Form):
    full_name = forms.CharField(label=_("Nome completo"), max_length=200)
    social_name = forms.CharField(label=_("Nome social"), max_length=200, required=False)
    birth_date = forms.DateField(label=_("Data de nascimento"), required=False, widget=_date_input())
    sex = forms.ChoiceField(label=_("Sexo"), choices=Patient.Sex.choices, initial=Patient.Sex.UNKNOWN)
    cpf = forms.CharField(label=_("CPF"), max_length=14, required=False)
    national_health_card = forms.CharField(label=_("Cartão Nacional de Saúde"), max_length=18, required=False)
    identity_document = forms.CharField(label=_("Documento de identidade"), max_length=30, required=False)
    mother_name = forms.CharField(label=_("Nome da mãe"), max_length=200, required=False)
    phone = forms.CharField(label=_("Telefone"), max_length=20, required=False)
    phone_secondary = forms.CharField(label=_("Outro telefone"), max_length=20, required=False)
    email = forms.EmailField(label=_("Email"), required=False)
    contact_preference = forms.ChoiceField(
        label=_("Preferência de contato"), choices=Patient.ContactPreference.choices, initial="phone"
    )
    postal_code = forms.CharField(label=_("CEP"), max_length=9, required=False)
    street = forms.CharField(label=_("Logradouro"), max_length=120, required=False)
    number = forms.CharField(label=_("Número"), max_length=20, required=False)
    complement = forms.CharField(label=_("Complemento"), max_length=60, required=False)
    district = forms.CharField(label=_("Bairro"), max_length=80, required=False)
    city = forms.CharField(label=_("Cidade"), max_length=80, required=False)
    state = forms.ChoiceField(
        label=_("UF"), choices=[("", "—"), *((code, code) for code in sorted(STATES))], required=False
    )
    notes = forms.CharField(
        label=_("Observações administrativas"),
        required=False,
        widget=forms.Textarea(attrs={"rows": 3}),
        help_text=_("Nunca registre aqui informação clínica: ela pertence ao prontuário."),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        keep_private(
            self,
            cpf=NUMERIC,
            national_health_card=NUMERIC,
            postal_code=NUMERIC,
            phone=PHONE,
            phone_secondary=PHONE,
            email=EMAIL,
        )


class StatusForm(forms.Form):
    status = forms.ChoiceField(label=_("Situação"), choices=Patient.Status.choices)
    deceased_on = forms.DateField(label=_("Data do óbito"), required=False, widget=_date_input())


class GuardianForm(forms.Form):
    name = forms.CharField(label=_("Nome"), max_length=200)
    relationship = forms.ChoiceField(label=_("Relação"), choices=PatientGuardian.Relationship.choices)
    cpf = forms.CharField(label=_("CPF"), max_length=14, required=False)
    phone = forms.CharField(label=_("Telefone"), max_length=20, required=False)
    email = forms.EmailField(label=_("Email"), required=False)
    is_legal_representative = forms.BooleanField(label=_("Representante legal"), required=False)
    is_financial_responsible = forms.BooleanField(label=_("Responsável financeiro"), required=False)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        keep_private(self, cpf=NUMERIC, phone=PHONE, email=EMAIL)

    notes = forms.CharField(label=_("Observações"), required=False, widget=forms.Textarea(attrs={"rows": 2}))


class CoverageForm(forms.Form):
    insurer_name = forms.CharField(label=_("Operadora"), max_length=120)
    insurer_code = forms.CharField(label=_("Registro ANS"), max_length=6, required=False)
    plan_name = forms.CharField(label=_("Plano"), max_length=120, required=False)
    card_number = forms.CharField(label=_("Número da carteirinha"), max_length=40)
    holder_name = forms.CharField(label=_("Titular"), max_length=200, required=False)
    valid_until = forms.DateField(label=_("Validade"), required=False, widget=_date_input())
    is_primary = forms.BooleanField(label=_("Convênio principal"), required=False)


class ConsentForm(forms.Form):
    purpose = forms.ChoiceField(label=_("Finalidade"))
    collected_via = forms.ChoiceField(label=_("Forma de coleta"), choices=Consent.CollectedVia.choices)
    term_version = forms.CharField(label=_("Versão do termo"), max_length=40, required=False)
    evidence_note = forms.CharField(
        label=_("Observação da coleta"), required=False, widget=forms.Textarea(attrs={"rows": 2})
    )

    def __init__(self, *args, purposes=(), **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["purpose"].choices = [(purpose.code, purpose.label) for purpose in purposes]


class TermForm(forms.Form):
    term = forms.FileField(label=_("Termo digitalizado (PDF, JPEG ou PNG)"))


class SetupForm(forms.Form):
    name = forms.CharField(label=_("Nome do cadastro"), max_length=120, initial=_("Pacientes da clínica"))
    writer_groups = forms.MultipleChoiceField(
        label=_("Grupos que cadastram e alteram pacientes"), required=False, widget=forms.CheckboxSelectMultiple
    )
    reader_groups = forms.MultipleChoiceField(
        label=_("Grupos que só consultam"), required=False, widget=forms.CheckboxSelectMultiple
    )

    def __init__(self, *args, groups=(), **kwargs):
        super().__init__(*args, **kwargs)
        choices = [(str(group.sysid), group.name) for group in groups]
        self.fields["writer_groups"].choices = choices
        self.fields["reader_groups"].choices = choices


def apply_service_errors(form: forms.Form, error) -> None:
    """Put the field errors of an InvalidInput on the form (unknown fields go to the top)."""
    for field, texts in error.errors.items():
        target = field if field in form.fields else None
        for text in texts:
            form.add_error(target, text)


class ImportUploadForm(forms.Form):
    file = forms.FileField(label=_("Arquivo CSV (UTF-8 ou Windows-1252, separado por vírgula ou ponto e vírgula)"))


class ImportMappingForm(forms.Form):
    """One select per column of the file: which patient field it feeds (or none)."""

    def __init__(self, *args, columns=(), mapping=None, fields=(), **kwargs):
        super().__init__(*args, **kwargs)
        choices = [("", _("Não importar")), *fields]
        mapping = mapping or {}
        self.columns = list(columns)
        for index, column in enumerate(self.columns):
            self.fields[f"column_{index}"] = forms.ChoiceField(
                label=column, choices=choices, required=False, initial=mapping.get(column, "")
            )

    def mapping(self):
        return tuple(
            (column, self.cleaned_data.get(f"column_{index}") or "")
            for index, column in enumerate(self.columns)
            if self.cleaned_data.get(f"column_{index}")
        )
