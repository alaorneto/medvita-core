"""Forms of the scheduling pages: format only. The rules live in SchedulingService."""

from __future__ import annotations

from django import forms
from django.utils.translation import gettext_lazy as _

from .models import COLORS, Appointment, Professional, Room, ScheduleBlock, WaitlistEntry

WEEKDAYS = (
    (0, _("Segunda")),
    (1, _("Terça")),
    (2, _("Quarta")),
    (3, _("Quinta")),
    (4, _("Sexta")),
    (5, _("Sábado")),
    (6, _("Domingo")),
)


def _date() -> forms.DateInput:
    return forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d")


def _time() -> forms.TimeInput:
    return forms.TimeInput(attrs={"type": "time"}, format="%H:%M")


class BookForm(forms.Form):
    schedule = forms.ChoiceField(label=_("Agenda"))
    appointment_type = forms.ChoiceField(label=_("Tipo de atendimento"))
    day = forms.DateField(label=_("Data"), widget=_date())
    slot = forms.CharField(label=_("Horário"), required=False, widget=forms.HiddenInput)
    fit_in = forms.BooleanField(label=_("Encaixe (fora da grade)"), required=False)
    fit_in_time = forms.TimeField(label=_("Hora do encaixe"), required=False, widget=_time())
    payment_kind = forms.ChoiceField(
        label=_("Pagamento"), choices=Appointment.PaymentKind.choices, required=False, initial="private"
    )
    notes = forms.CharField(
        label=_("Observação da recepção"),
        required=False,
        widget=forms.Textarea(attrs={"rows": 2}),
        help_text=_("Fica visível só para quem lê a agenda e nunca sai em notificação."),
    )

    def __init__(self, *args, schedules=(), types=(), **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["schedule"].choices = [(str(item.sysid), item.name) for item in schedules if item.writable]
        self.fields["appointment_type"].choices = [(str(item.sysid), item.name) for item in types]


class RescheduleForm(forms.Form):
    day = forms.DateField(label=_("Nova data"), widget=_date())
    time = forms.TimeField(label=_("Nova hora"), widget=_time())


class CancelForm(forms.Form):
    reason = forms.ChoiceField(label=_("Motivo"), choices=Appointment.CancelReason.choices)
    note = forms.CharField(label=_("Observação"), required=False, max_length=200)


class PracticeForm(forms.Form):
    name = forms.CharField(label=_("Nome do consultório"), max_length=120)
    legal_name = forms.CharField(label=_("Razão social"), max_length=200, required=False)
    tax_id = forms.CharField(label=_("CPF ou CNPJ"), max_length=18, required=False)
    phone = forms.CharField(label=_("Telefone"), max_length=20, required=False)
    email = forms.EmailField(label=_("Email"), required=False)
    address = forms.CharField(label=_("Endereço"), max_length=300, required=False)
    city = forms.CharField(label=_("Cidade"), max_length=80, required=False)
    state = forms.CharField(label=_("UF"), max_length=2, required=False)
    timezone = forms.CharField(label=_("Fuso horário"), max_length=64)


class ProfessionalForm(forms.Form):
    display_name = forms.CharField(label=_("Nome"), max_length=200)
    council = forms.ChoiceField(label=_("Conselho"), choices=Professional.Council.choices)
    council_number = forms.CharField(label=_("Número no conselho"), max_length=20, required=False)
    council_state = forms.CharField(label=_("UF do conselho"), max_length=2, required=False)
    specialty = forms.CharField(label=_("Especialidade"), max_length=120, required=False)
    member = forms.ChoiceField(label=_("Pessoa da organização (opcional)"), required=False)

    def __init__(self, *args, members=(), **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["member"].choices = [("", "—"), *((str(item.sysid), item.display_name) for item in members)]


class RoomForm(forms.Form):
    name = forms.CharField(label=_("Nome"), max_length=80)
    kind = forms.ChoiceField(label=_("Tipo"), choices=Room.Kind.choices)


class TypeForm(forms.Form):
    code = forms.SlugField(label=_("Código"), max_length=40)
    name = forms.CharField(label=_("Nome"), max_length=120)
    duration_minutes = forms.IntegerField(label=_("Duração (minutos)"), min_value=5, max_value=480, initial=30)
    color = forms.ChoiceField(label=_("Cor"), choices=[(color, color) for color in COLORS])
    billing_code = forms.CharField(label=_("Código de cobrança"), max_length=40, required=False)
    requires_room = forms.BooleanField(label=_("Exige sala"), required=False)


class ScheduleForm(forms.Form):
    name = forms.CharField(label=_("Nome da agenda"), max_length=120)
    professional = forms.ChoiceField(label=_("Profissional"), required=False)
    room = forms.ChoiceField(label=_("Sala"), required=False)
    slot_minutes = forms.IntegerField(label=_("Intervalo (minutos)"), min_value=5, max_value=120, initial=30)
    writer_groups = forms.MultipleChoiceField(
        label=_("Grupos que marcam"), required=False, widget=forms.CheckboxSelectMultiple
    )
    reader_groups = forms.MultipleChoiceField(
        label=_("Grupos que só consultam"), required=False, widget=forms.CheckboxSelectMultiple
    )

    def __init__(self, *args, professionals=(), rooms=(), groups=(), **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["professional"].choices = [
            ("", "—"),
            *((str(item.sysid), item.display_name) for item in professionals),
        ]
        self.fields["room"].choices = [("", "—"), *((str(item.sysid), item.name) for item in rooms)]
        group_choices = [(str(group.sysid), group.name) for group in groups]
        self.fields["writer_groups"].choices = group_choices
        self.fields["reader_groups"].choices = group_choices


class AvailabilityForm(forms.Form):
    """Up to two windows per weekday, HH:MM; empty fields mean no window."""

    valid_from = forms.DateField(label=_("Válida a partir de"), widget=_date())

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for weekday, label in WEEKDAYS:
            for slot in (1, 2):
                self.fields[f"d{weekday}_{slot}_start"] = forms.TimeField(
                    label=f"{label} · {_('início')} {slot}", required=False, widget=_time()
                )
                self.fields[f"d{weekday}_{slot}_end"] = forms.TimeField(
                    label=f"{label} · {_('fim')} {slot}", required=False, widget=_time()
                )


class BlockForm(forms.Form):
    day = forms.DateField(label=_("Dia"), widget=_date())
    start = forms.TimeField(label=_("Início"), widget=_time())
    end = forms.TimeField(label=_("Fim"), widget=_time())
    reason = forms.ChoiceField(label=_("Motivo"), choices=ScheduleBlock.Reason.choices)
    note = forms.CharField(label=_("Observação"), max_length=200, required=False)


class WaitlistForm(forms.Form):
    patient_code = forms.CharField(label=_("Código do paciente (P000001)"), max_length=20)
    appointment_type = forms.ChoiceField(label=_("Tipo de atendimento"), required=False)
    preferred_period = forms.ChoiceField(label=_("Período"), choices=WaitlistEntry.Period.choices)
    earliest_date = forms.DateField(label=_("A partir de"), widget=_date())
    latest_date = forms.DateField(label=_("Até"), required=False, widget=_date())
    priority = forms.ChoiceField(label=_("Prioridade"), choices=WaitlistEntry.Priority.choices)
    note = forms.CharField(label=_("Observação"), max_length=200, required=False)

    def __init__(self, *args, types=(), **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["appointment_type"].choices = [("", "—"), *((str(item.sysid), item.name) for item in types)]


class SetupForm(forms.Form):
    practice_name = forms.CharField(label=_("Nome do consultório"), max_length=120)
    timezone = forms.CharField(label=_("Fuso horário"), max_length=64, initial="America/Sao_Paulo")
    reader_groups = forms.MultipleChoiceField(
        label=_("Grupos que consultam a configuração"), required=False, widget=forms.CheckboxSelectMultiple
    )
    manager_groups = forms.MultipleChoiceField(
        label=_("Grupos que gerem a configuração e a lista de espera"),
        required=False,
        widget=forms.CheckboxSelectMultiple,
    )

    def __init__(self, *args, groups=(), **kwargs):
        super().__init__(*args, **kwargs)
        choices = [(str(group.sysid), group.name) for group in groups]
        self.fields["reader_groups"].choices = choices
        self.fields["manager_groups"].choices = choices


def apply_service_errors(form: forms.Form, error) -> None:
    for field, texts in error.errors.items():
        target = field if field in form.fields else None
        for text in texts:
            form.add_error(target, text)
