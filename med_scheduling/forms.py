"""Forms of the scheduling pages: format only. The rules live in SchedulingService."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, time
from typing import Any
from uuid import UUID

from django import forms
from django.utils.translation import gettext
from django.utils.translation import gettext_lazy as _

from .models import COLORS, Appointment, Mode, PaymentKind, Professional, Room, ScheduleBlock, WaitlistEntry
from .slots import collide

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
    """Schedule, kind, day and duration; the kinds offered are the ones the chosen schedule takes.

    ``suggested_duration`` carries the duration the page suggested, so the page tells a duration
    somebody typed from a suggestion nobody touched (which follows the kind when the kind changes).
    ``slot`` is the one choice of the page: a free time, or a walk-in period (``walk_in_value``).
    """

    WALK_IN_PREFIX = "walk_in:"

    schedule = forms.ChoiceField(label=_("Agenda"))
    appointment_type = forms.ChoiceField(
        label=_("Tipo de atendimento"),
        error_messages={"invalid_choice": _("Esta agenda não atende este tipo de atendimento. Escolha outro.")},
    )
    day = forms.DateField(label=_("Data"), widget=_date())
    # The data-* names are the hooks of the optional script, which does on the page what the
    # "Atualizar horários" button does on the server: an untouched duration follows the kind.
    duration = forms.IntegerField(
        label=_("Duração (minutos)"),
        min_value=5,
        max_value=480,
        required=False,
        widget=forms.NumberInput(attrs={"data-duration": "typed"}),
        help_text=_("Sugerida pelo tipo de atendimento nesta agenda. Altere se esta consulta precisar de outro tempo."),
    )
    suggested_duration = forms.IntegerField(
        required=False, widget=forms.HiddenInput(attrs={"data-duration": "suggested"})
    )
    slot = forms.CharField(label=_("Horário"), required=False, widget=forms.HiddenInput)
    fit_in = forms.BooleanField(label=_("Encaixe (fora da grade)"), required=False)
    fit_in_time = forms.TimeField(
        label=_("Hora do encaixe"),
        required=False,
        widget=_time(),
        help_text=_(
            "Para encaixar com hora marcada. Para encaixar num período de ordem de chegada, "
            "escolha o período acima e deixe a hora em branco."
        ),
    )
    arrived = forms.BooleanField(label=_("O paciente já está aqui: registrar a chegada agora"), required=False)
    priority = forms.BooleanField(
        label=_("Atendimento prioritário (Lei 10.048)"),
        required=False,
        help_text=_(
            "Põe o paciente à frente na fila da ordem de chegada. A marca aparece só na fila e na página da consulta."
        ),
    )
    # Not shown: the appointment is paid for as its kind says. Kept for whoever posts it.
    payment_kind = forms.ChoiceField(label=_("Forma de pagamento"), choices=PaymentKind.choices, required=False)
    notes = forms.CharField(
        label=_("Observação da recepção"),
        required=False,
        widget=forms.Textarea(attrs={"rows": 2}),
        help_text=_("Fica visível só para quem lê a agenda e nunca sai em notificação."),
    )

    def __init__(self, *args, schedules=(), type_choices=(), **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["schedule"].choices = [(str(item.sysid), item.name) for item in schedules if item.writable]
        self.fields["appointment_type"].choices = list(type_choices)

    @classmethod
    def walk_in_value(cls, starts_at) -> str:
        """The value of ``slot`` that chooses the walk-in period starting at the instant."""
        return f"{cls.WALK_IN_PREFIX}{starts_at.isoformat()}"


class RescheduleForm(forms.Form):
    """The new day and time of an appointment; ``walk_in`` says the appointment has no time of its own today."""

    day = forms.DateField(label=_("Nova data"), widget=_date())
    time = forms.TimeField(label=_("Nova hora"), widget=_time())
    mode = forms.ChoiceField(label=_("Modo de atendimento"), required=False)

    def __init__(self, *args, walk_in=False, **kwargs):
        super().__init__(*args, **kwargs)
        current = Mode.WALK_IN if walk_in else Mode.BOOKED
        self.fields["mode"].choices = [
            ("", gettext("Como está (%(mode)s)") % {"mode": current.label}),
            *((value, label) for value, label in Mode.choices if value != current),
        ]
        self.fields["time"].help_text = _(
            "Na ordem de chegada a consulta não tem hora: informe qualquer hora dentro do período de destino."
        )


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
    payment_kind = forms.ChoiceField(
        label=_("Forma de pagamento"),
        choices=PaymentKind.choices,
        initial=PaymentKind.PRIVATE,
        help_text=_("A consulta marcada com este tipo nasce com esta forma de pagamento."),
    )
    color = forms.ChoiceField(label=_("Cor"), choices=[(color, color) for color in COLORS])
    billing_code = forms.CharField(label=_("Código de cobrança"), max_length=40, required=False)
    requires_room = forms.BooleanField(label=_("Exige sala"), required=False)


class TypeEditForm(TypeForm):
    """A kind of appointment that already exists: everything but the code, which never changes."""

    code = None
    is_active = forms.BooleanField(
        label=_("Ativo"),
        required=False,
        help_text=_("Um tipo inativo deixa de ser oferecido ao marcar. As consultas já marcadas não mudam."),
    )


class ScheduleTypesForm(forms.Form):
    """The kinds a schedule takes: every kind of the practice, or the ticked ones with their duration there."""

    ALL, CHOSEN = "all", "chosen"

    scope = forms.ChoiceField(
        label=_("Esta agenda atende"),
        choices=(
            (ALL, _("Todos os tipos de atendimento do consultório")),
            (CHOSEN, _("Só os tipos marcados abaixo")),
        ),
        widget=forms.RadioSelect,
    )

    def __init__(self, *args, kinds=(), **kwargs):
        super().__init__(*args, **kwargs)
        self.kinds = tuple(kinds)
        for kind in self.kinds:
            self.fields[self.on(kind)] = forms.BooleanField(
                label=gettext("Atende %(name)s") % {"name": kind.name}, required=False
            )
            self.fields[self.minutes(kind)] = forms.IntegerField(
                label=gettext("Duração de %(name)s nesta agenda (minutos)") % {"name": kind.name},
                min_value=5,
                max_value=480,
                required=False,
            )
            self.fields[self.booked(kind)] = forms.BooleanField(
                label=gettext("%(name)s com hora marcada") % {"name": kind.name}, required=False, initial=True
            )
            self.fields[self.walk_in(kind)] = forms.BooleanField(
                label=gettext("%(name)s por ordem de chegada") % {"name": kind.name}, required=False, initial=True
            )

    @staticmethod
    def on(kind) -> str:
        return f"on_{kind.sysid.hex}"

    @staticmethod
    def minutes(kind) -> str:
        return f"minutes_{kind.sysid.hex}"

    @staticmethod
    def booked(kind) -> str:
        return f"booked_{kind.sysid.hex}"

    @staticmethod
    def walk_in(kind) -> str:
        return f"walk_in_{kind.sysid.hex}"

    def rows(self) -> list[dict]:
        return [
            {
                "kind": kind,
                "on": self[self.on(kind)],
                "minutes": self[self.minutes(kind)],
                "booked": self[self.booked(kind)],
                "walk_in": self[self.walk_in(kind)],
            }
            for kind in self.kinds
        ]

    def clean(self):
        data = super().clean()
        if data.get("scope") != self.CHOSEN:
            return data
        ticked = [kind for kind in self.kinds if data.get(self.on(kind))]
        if not ticked:
            self.add_error(None, _("Marque ao menos um tipo de atendimento, ou escolha atender todos."))
        for kind in ticked:
            if not (data.get(self.booked(kind)) or data.get(self.walk_in(kind))):
                self.add_error(
                    self.booked(kind),
                    gettext("Marque como a agenda atende %(name)s: com hora marcada, por ordem de chegada ou os dois.")
                    % {"name": kind.name},
                )
        return data

    def chosen(self) -> list[tuple]:
        """(kind id, own duration or None, booked, walk-in) of each ticked kind; empty when the schedule takes them all."""
        data = self.cleaned_data
        if data["scope"] == self.ALL:
            return []
        return [
            (
                kind.sysid,
                data.get(self.minutes(kind)),
                bool(data.get(self.booked(kind))),
                bool(data.get(self.walk_in(kind))),
            )
            for kind in self.kinds
            if data.get(self.on(kind))
        ]


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


def clock(minutes: int) -> str:
    """Minutes of the day as the page shows them; the end of the day is 24:00."""
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def _minute(value: time, *, end: bool = False) -> int:
    """Minutes of the day of a typed time; midnight as the end of a period is the end of the day."""
    minutes = value.hour * 60 + value.minute
    return 1440 if end and minutes == 0 else minutes


@dataclass(frozen=True)
class Period:
    """A weekly period as a form read it, in the shape the grid compares (``slots.collide``)."""

    weekday: int
    start_minute: int
    end_minute: int
    valid_from: date
    valid_until: date | None
    kinds: tuple[UUID, ...] = ()
    field: str = ""  # the field of the form the period was typed in
    mode: str = Mode.BOOKED.value
    capacity: int | None = None


class Boxes(forms.CheckboxSelectMultiple):
    """Checkboxes whose field has an id to link to: the one of the first box (the error summary uses it)."""

    def id_for_label(self, id_, index=None):
        return super().id_for_label(id_, "0" if index is None else index)


class PeriodBase(forms.Form):
    """What every period of the weekly grid has: its mode, the kinds it takes and when it is valid.

    ``kinds`` are the kinds the schedule takes; ``existing`` the periods the grid already has (but
    the one being changed), against which an overlap is told on the field that caused it.
    ``walk_in_kinds`` and ``booked_kinds`` are the ids of the kinds the schedule takes in each mode.
    """

    # The data-* names are the hooks of the optional script, which folds "Vagas" away in booked time.
    mode = forms.ChoiceField(
        label=_("Modo de atendimento"),
        choices=Mode.choices,
        initial=Mode.BOOKED,
        required=False,  # A form sent without it is of booked time, as every period was before the modes.
        widget=forms.Select(attrs={"data-period-mode": ""}),
        help_text=_(
            "Com hora marcada, cada paciente tem o seu horário. Por ordem de chegada, os pacientes são "
            "marcados para o período e atendidos na ordem em que chegam."
        ),
    )
    capacity = forms.IntegerField(
        label=_("Vagas"),
        min_value=1,
        max_value=500,
        required=False,
        help_text=_(
            "Só na ordem de chegada: quantos pacientes o período comporta. Em branco, comporta o que couber no tempo dele."
        ),
    )
    kinds = forms.MultipleChoiceField(
        label=_("Tipos de atendimento do período"),
        required=False,
        widget=Boxes,
        help_text=_("Sem nenhum marcado, o período atende todos os tipos que a agenda atende."),
    )
    valid_from = forms.DateField(label=_("Vale a partir de"), widget=_date())
    valid_until = forms.DateField(
        label=_("Vale até"),
        required=False,
        widget=_date(),
        help_text=_("Em branco, o período vale sem data para terminar."),
    )

    def __init__(self, *args, kinds=(), existing=(), booked_kinds=None, walk_in_kinds=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["kinds"].choices = [(str(kind.sysid), kind.name) for kind in kinds]
        self.existing = tuple(existing)
        self._names = {kind.sysid: kind.name for kind in kinds}
        every = set(self._names)
        self._taken = {
            Mode.BOOKED.value: every if booked_kinds is None else set(booked_kinds),
            Mode.WALK_IN.value: every if walk_in_kinds is None else set(walk_in_kinds),
        }

    def _mode(self, data: dict[str, Any]) -> tuple[str, int | None] | None:
        """The mode and the capacity typed; ``None`` (with the error on the field) when they do not go together."""
        if "mode" in self.errors or "capacity" in self.errors:
            return None
        mode, capacity = data.get("mode") or Mode.BOOKED.value, data.get("capacity")
        if mode != Mode.WALK_IN and capacity is not None:
            self.add_error(
                "capacity",
                _("Vagas valem só na ordem de chegada. Apague as vagas, ou troque o modo de atendimento do período."),
            )
            return None
        refused = [self._names[kind] for kind in self._kinds(data) if kind not in self._taken[mode]]
        if refused:
            texts = {
                Mode.WALK_IN.value: gettext("A agenda não atende por ordem de chegada: %(names)s."),
                Mode.BOOKED.value: gettext("A agenda não atende com hora marcada: %(names)s."),
            }
            self.add_error("kinds", texts[mode] % {"names": ", ".join(refused)})
            return None
        return mode, capacity

    def _line(self, data: dict[str, Any], start: str, end: str) -> tuple[int, int] | None:
        """The minutes of a start and end pair; ``None`` (with the error on the field) when it is not a period."""
        first, last = data.get(start), data.get(end)
        if first is None or last is None:
            if (first is None) != (last is None) and not (self.errors.get(start) or self.errors.get(end)):
                self.add_error(start if first is None else end, _("Informe o início e o fim do período."))
            return None
        minutes = (_minute(first), _minute(last, end=True))
        if minutes[0] >= minutes[1]:
            self.add_error(end, _("O fim precisa ser depois do início, no mesmo dia."))
            return None
        return minutes

    def _validity(self, data: dict[str, Any]) -> bool:
        first, last = data.get("valid_from"), data.get("valid_until")
        if first is None:
            return False
        if last is not None and last < first:
            self.add_error("valid_until", _("A validade termina antes de começar."))
            return False
        return True

    def _refuse_overlaps(self, periods: list[Period]) -> None:
        """An overlap with the grid, or between the periods typed, goes to the field of the period."""
        weekdays = dict(WEEKDAYS)
        accepted: list[Any] = list(self.existing)
        for period in periods:
            other = next((item for item in accepted if collide(period, item)), None)
            if other is None:
                accepted.append(period)
                continue
            self.add_error(
                period.field,
                gettext(
                    "%(weekday)s: %(start)s–%(end)s se sobrepõe ao período %(other_start)s–%(other_end)s. "
                    "Ajuste o horário, ou altere o período que já existe."
                )
                % {
                    "weekday": weekdays[period.weekday],
                    "start": clock(period.start_minute),
                    "end": clock(period.end_minute),
                    "other_start": clock(other.start_minute),
                    "other_end": clock(other.end_minute),
                },
            )

    def _kinds(self, data: dict[str, Any]) -> tuple[UUID, ...]:
        return tuple(UUID(value) for value in data.get("kinds", ()))


class PeriodsForm(PeriodBase):
    """New periods of the weekly grid: each hour line becomes a period on every ticked weekday."""

    LINES = (1, 2, 3)

    weekdays = forms.MultipleChoiceField(
        label=_("Dias da semana"),
        choices=WEEKDAYS,
        widget=Boxes,
        error_messages={"required": _("Marque ao menos um dia da semana.")},
    )
    field_order = (
        "weekdays",
        *(f"{name}_{line}" for line in LINES for name in ("start", "end")),
        "mode",
        "capacity",
        "kinds",
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for line in self.LINES:
            for name, label in (("start", _("Início do horário %(line)s")), ("end", _("Fim do horário %(line)s"))):
                self.fields[f"{name}_{line}"] = forms.TimeField(
                    label=label % {"line": line}, required=line == 1, widget=_time()
                )
        self.order_fields(self.field_order)

    def lines(self) -> list[dict[str, Any]]:
        """The hour lines for the page: number, the two fields and whether the line came empty."""
        return [
            {
                "number": line,
                "start": self[f"start_{line}"],
                "end": self[f"end_{line}"],
                "empty": not (self[f"start_{line}"].value() or self[f"end_{line}"].value()),
            }
            for line in self.LINES
        ]

    def clean(self):
        data = super().clean()
        hours = [(line, self._line(data, f"start_{line}", f"end_{line}")) for line in self.LINES]
        valid = self._validity(data)
        mode = self._mode(data)
        self.periods: list[Period] = []
        if self.errors or not valid or mode is None:
            return data
        self.periods = [
            Period(
                int(weekday),
                minutes[0],
                minutes[1],
                data["valid_from"],
                data["valid_until"],
                self._kinds(data),
                f"start_{line}",
                *mode,
            )
            for weekday in sorted(data["weekdays"], key=int)
            for line, minutes in hours
            if minutes is not None
        ]
        self._refuse_overlaps(self.periods)
        if self.errors:
            self.periods = []
        return data


class PeriodForm(PeriodBase):
    """One period of the weekly grid that already exists."""

    weekday = forms.TypedChoiceField(label=_("Dia da semana"), choices=WEEKDAYS, coerce=int)
    start = forms.TimeField(label=_("Início"), widget=_time())
    end = forms.TimeField(label=_("Fim"), widget=_time())
    field_order = ("weekday", "start", "end", "mode", "capacity", "kinds")

    def clean(self):
        data = super().clean()
        minutes = self._line(data, "start", "end")
        valid = self._validity(data)
        mode = self._mode(data)
        self.period: Period | None = None
        if self.errors or not valid or minutes is None or mode is None:
            return data
        self.period = Period(
            data["weekday"],
            minutes[0],
            minutes[1],
            data["valid_from"],
            data["valid_until"],
            self._kinds(data),
            "start",
            *mode,
        )
        self._refuse_overlaps([self.period])
        if self.errors:
            self.period = None
        return data


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


def apply_service_errors(form: forms.Form, error, aliases: dict[str, str] | None = None) -> None:
    """Put the errors of a service on the fields of the form; ``aliases`` names the field of a service key."""
    for field, texts in error.errors.items():
        field = (aliases or {}).get(field, field)
        target = field if field in form.fields else None
        for text in texts:
            form.add_error(target, text)
