# API de serviços: Agenda médica

Referência de `SchedulingService` (`applications.med_scheduling.service_api`). O contrato geral está na [API de serviços do núcleo](https://github.com/alaorneto/skeleton/blob/f38c9a02166d63e402d2c7708e616ae842441665/docs/service-api.md).

## Visão geral

`SchedulingService` dá às outras apps e às superfícies desta app o consultório, as agendas, as consultas e a lista de espera da organização atual, com a autorização do ator do contexto. Todos os métodos exigem a app ativa (`Unavailable`), contexto de organização e `actor` igual ao do contexto. Comandos rodam num savepoint da transação do chamador. Registro inexistente, de outra organização ou ilegível respondem o mesmo `NotFound`.

## Dependência

`app_id`: `io.katua.sk.med.scheduling`. Faixa no manifesto do consumidor: a versão corrente da suíte, `>=0.1.0,<0.2.0` na primeira linha. Importe só o módulo `service_api` desta app.

<!-- BEGIN GENERATED: tools/service_reference.py -->

## Serviços

### `SchedulingService`

#### `add_appointment_type(*, actor, code, name, duration_minutes=30, color='blue', billing_code='', requires_room=False, idempotency_key=None) -> AppointmentTypeInfo`

Add a kind of appointment; the code is unique in the practice.

- **Autorização:** alteração no consultório.
- **Erros:** NotFound; Forbidden; InvalidInput; Conflict("integrity_conflict") para código já usado.
- **Efeitos:** grava o tipo; a mesma chave do mesmo ator devolve o já criado.

#### `add_block(*, actor, schedule_id, starts_at, ends_at, reason='other', note='', idempotency_key=None) -> BlockInfo`

Block a period of a schedule; it shows as busy in the schedule's calendar too.

- **Autorização:** alteração na agenda.
- **Erros:** NotFound; Forbidden; InvalidInput para período sem fuso ou invertido, motivo desconhecido ou observação acima de 200 caracteres.
- **Efeitos:** grava o bloqueio e o projeta no calendário como evento gerenciado ("Bloqueio").

#### `add_room(*, actor, name, kind='room', idempotency_key=None) -> RoomInfo`

Add a room or a piece of equipment.

- **Autorização:** alteração no consultório.
- **Erros:** NotFound; Forbidden; InvalidInput.
- **Efeitos:** grava a sala; a mesma chave do mesmo ator devolve a já criada.

#### `add_to_waitlist(*, actor, patient_id, earliest_date, appointment_type_id=None, schedule_id=None, preferred_period='any', latest_date=None, priority='normal', note='', idempotency_key) -> WaitlistInfo`

Put a patient on the waitlist of the practice.

- **Autorização:** alteração no consultório e leitura do paciente.
- **Erros:** NotFound (consultório, paciente, tipo ou agenda ilegível); Forbidden se só lê o consultório; InvalidInput para período, prioridade, datas ou observação inválidos; Conflict("patient_inactive", "processing_restricted").
- **Efeitos:** grava a entrada; a mesma chave do mesmo ator devolve a já criada.

#### `appointment(*, actor, appointment_id) -> AppointmentDetail`

One appointment with its notes and the times of each state.

- **Autorização:** leitura da agenda.
- **Erros:** NotFound para consulta inexistente, de outra organização ou ilegível.
- **Efeitos:** nenhum.

#### `appointment_actions(*, actor, appointment_id) -> tuple[AppointmentActionInfo, ...]`

Actions other apps registered for the current state of an appointment, in order.

- **Autorização:** leitura da agenda (cada ação autoriza a própria página).
- **Erros:** NotFound para consulta ilegível.
- **Efeitos:** nenhum.

#### `appointment_types(*, actor, active_only=True) -> tuple[AppointmentTypeInfo, ...]`

Kinds of appointment of the practice.

- **Autorização:** leitura do consultório.
- **Erros:** NotFound sem consultório legível.
- **Efeitos:** nenhum.

#### `appointments(*, actor, schedule_id=None, patient_id=None, start=None, end=None, status=None, cursor=None, page_size=50) -> Page[AppointmentInfo]`

Appointments of the schedules the actor reads, by start time, filtered.

- **Autorização:** leitura de cada agenda.
- **Erros:** InvalidInput para filtro, cursor ou tamanho de página inválidos.
- **Efeitos:** nenhum.

#### `availability(*, actor, schedule_id) -> tuple[AvailabilityRuleInfo, ...]`

The weekly grid of a schedule, by weekday and start.

- **Autorização:** leitura da agenda.
- **Erros:** NotFound para agenda ilegível.
- **Efeitos:** nenhum.

#### `available_slots(*, actor, schedule_id, start_date, end_date, appointment_type_id=None) -> tuple[Slot, ...]`

Free slots of a schedule between two dates (inclusive, at most 62 days).

- **Autorização:** leitura da agenda.
- **Erros:** NotFound para agenda ou tipo ilegível; InvalidInput para intervalo invertido ou acima de 62 dias.
- **Efeitos:** nenhum.

#### `blocks(*, actor, schedule_id, start, end) -> tuple[BlockInfo, ...]`

Blocks of a schedule that overlap a window.

- **Autorização:** leitura da agenda.
- **Erros:** NotFound; InvalidInput para janela sem fuso, invertida ou acima de 400 dias.
- **Efeitos:** nenhum.

#### `book(*, actor, schedule_id, patient_id, appointment_type_id, starts_at, duration_minutes=None, fit_in=False, notes='', payment_kind='private', room_id=None, idempotency_key) -> AppointmentInfo`

Book an appointment; a fit-in skips the grid and the overlap check, never a block.

- **Autorização:** alteração na agenda e leitura do paciente.
- **Erros:** NotFound (agenda, paciente, tipo ou sala ilegível); Forbidden se só lê a agenda; InvalidInput (horário sem fuso, duração fora de 5 a 480, forma de pagamento, observação longa, sala exigida pelo tipo); Conflict("slot_unavailable", "room_unavailable", "patient_inactive", "processing_restricted").
- **Efeitos:** código da sequência sem lacunas, consulta gravada, evento no calendário e ``med_scheduling.appointment_booked`` publicados; a mesma chave devolve a já marcada.

#### `book_from_waitlist(*, actor, entry_id, schedule_id, starts_at, expected_revision, idempotency_key) -> AppointmentInfo`

Book the appointment of a waiting patient and mark the entry booked, in one transaction.

- **Autorização:** alteração no consultório e na agenda.
- **Erros:** NotFound; Forbidden; InvalidInput sem tipo de atendimento na entrada; Conflict("stale_revision", "invalid_transition", "slot_unavailable"): com o horário ocupado a entrada continua aguardando.
- **Efeitos:** os de ``book`` e a entrada em "agendado" com a consulta.

#### `cancel(*, actor, appointment_id, reason, expected_revision, note='') -> AppointmentInfo`

Cancel an appointment (scheduled, confirmed or arrived), with CAS.

- **Autorização:** alteração na agenda.
- **Erros:** NotFound; Forbidden; InvalidInput para motivo desconhecido ou observação acima de 200 caracteres; Conflict("stale_revision", "invalid_transition").
- **Efeitos:** grava a situação e o motivo, remove o evento do calendário e publica ``med_scheduling.appointment_cancelled``.

#### `cancel_waitlist_entry(*, actor, entry_id, expected_revision) -> WaitlistInfo`

Take a patient off the waitlist, with CAS.

- **Autorização:** alteração no consultório.
- **Erros:** NotFound; Forbidden; Conflict("stale_revision", "invalid_transition") fora de "aguardando".
- **Efeitos:** grava a situação "cancelado".

#### `check_in(*, actor, appointment_id, expected_revision) -> AppointmentInfo`

Register that the patient arrived, with CAS, and tell the professional.

- **Autorização:** alteração na agenda.
- **Erros:** NotFound; Forbidden; Conflict("stale_revision", "invalid_transition").
- **Efeitos:** grava a situação e a hora, publica ``med_scheduling.appointment_arrived`` e notifica o profissional da agenda (uma vez por consulta; a notificação leva o código, nunca o paciente).

#### `complete(*, actor, appointment_id, expected_revision) -> AppointmentInfo`

Finish an appointment (arrived or in progress), with CAS.

- **Autorização:** alteração na agenda.
- **Erros:** NotFound; Forbidden; Conflict("stale_revision", "invalid_transition").
- **Efeitos:** grava a situação e a hora e publica ``med_scheduling.appointment_completed``.

#### `confirm(*, actor, appointment_id, expected_revision) -> AppointmentInfo`

Confirm a scheduled appointment, with CAS.

- **Autorização:** alteração na agenda.
- **Erros:** NotFound; Forbidden; Conflict("stale_revision", "invalid_transition").
- **Efeitos:** grava a situação e a hora e publica ``med_scheduling.appointment_confirmed``.

#### `create_schedule(*, actor, name, professional_id=None, room_id=None, slot_minutes=30, writer_group_ids=(), reader_group_ids=(), writer_user_ids=(), idempotency_key) -> ScheduleInfo`

Create the schedule of a professional or room, with its shared calendar and the same access.

- **Autorização:** a capacidade ``access.manage`` e ``create`` em med_scheduling.schedule.
- **Erros:** Forbidden; NotFound para profissional ou sala ilegível; InvalidInput para nome vazio, sem profissional nem sala, intervalo fora de 5 a 120 minutos, mais de 20 grupos ou pessoas; Unavailable com a agenda do núcleo desativada.
- **Efeitos:** cria o calendário compartilhado, a agenda e as concessões nas duas, na transação do chamador; a mesma chave do mesmo ator devolve a agenda já criada.

#### `day(*, actor, date, schedule_ids=None) -> tuple[DayAgenda, ...]`

The appointments and free slots of one local day, for every schedule the actor reads.

- **Autorização:** leitura de cada agenda.
- **Erros:** InvalidInput para data inválida ou mais de 20 agendas.
- **Efeitos:** nenhum.

#### `mark_no_show(*, actor, appointment_id, expected_revision) -> AppointmentInfo`

Mark that the patient did not come (only after the start time), with CAS.

- **Autorização:** alteração na agenda.
- **Erros:** NotFound; Forbidden; Conflict("stale_revision", "invalid_transition").
- **Efeitos:** grava a situação, mantém o evento no calendário e publica ``med_scheduling.appointment_no_show``.

#### `my_professional(*, actor) -> ProfessionalInfo | None`

The active professional record linked to the actor, or ``None``.

- **Autorização:** leitura do consultório.
- **Erros:** nenhum além do contrato; sem consultório legível, ``None``.
- **Efeitos:** nenhum.

#### `practice(*, actor) -> PracticeInfo`

The default practice of the organization.

- **Autorização:** leitura do consultório.
- **Erros:** NotFound sem consultório configurado ou sem leitura.
- **Efeitos:** nenhum.

#### `professional(*, actor, professional_id) -> ProfessionalInfo`

One professional.

- **Autorização:** leitura do consultório.
- **Erros:** NotFound para profissional inexistente, de outra organização ou ilegível.
- **Efeitos:** nenhum.

#### `professionals(*, actor, active_only=True) -> tuple[ProfessionalInfo, ...]`

Professionals of the practice, by name.

- **Autorização:** leitura do consultório.
- **Erros:** NotFound sem consultório legível.
- **Efeitos:** nenhum.

#### `register_professional(*, actor, display_name, council='crm', council_number='', council_state='', specialty='', rqe='', tax_id='', membership_user_id=None, idempotency_key=None) -> ProfessionalInfo`

Register a professional of the practice, optionally linked to a member of the organization.

- **Autorização:** alteração no consultório.
- **Erros:** NotFound sem consultório; Forbidden se só lê; InvalidInput com o nome do campo ou para pessoa que não é membro ativo; Conflict("integrity_conflict") para pessoa já ligada a outro profissional vivo; Conflict("quota_exceeded") acima do limite de profissionais do plano.
- **Efeitos:** grava o profissional; a mesma chave do mesmo ator devolve o já criado.

#### `remove_block(*, actor, block_id, expected_revision) -> None`

Remove a block of a schedule, with CAS, and its calendar event.

- **Autorização:** alteração na agenda.
- **Erros:** NotFound; Forbidden; Conflict("stale_revision").
- **Efeitos:** exclusão lógica do bloqueio e do evento projetado.

#### `reschedule(*, actor, appointment_id, starts_at, expected_revision, schedule_id=None, idempotency_key=None) -> AppointmentInfo`

Move an appointment to another time (same duration), with CAS; to another schedule, a new one.

- **Autorização:** alteração na agenda atual (e na nova, quando outra).
- **Erros:** NotFound; Forbidden; InvalidInput; Conflict("stale_revision", "invalid_transition", "slot_unavailable", "room_unavailable").
- **Efeitos:** atualiza (ou cancela e cria) a consulta e o evento do calendário e publica ``appointment_rescheduled`` (ou ``appointment_cancelled`` e ``appointment_booked``).

#### `rooms(*, actor, active_only=True) -> tuple[RoomInfo, ...]`

Rooms and equipment of the practice.

- **Autorização:** leitura do consultório.
- **Erros:** NotFound sem consultório legível.
- **Efeitos:** nenhum.

#### `schedule(*, actor, schedule_id) -> ScheduleInfo`

One schedule.

- **Autorização:** leitura da agenda.
- **Erros:** NotFound para agenda inexistente, de outra organização ou ilegível.
- **Efeitos:** nenhum.

#### `schedules(*, actor, active_only=True) -> tuple[ScheduleInfo, ...]`

Schedules the actor reads, by name.

- **Autorização:** leitura de cada agenda.
- **Erros:** Forbidden sem a permissão de tabela das agendas.
- **Efeitos:** nenhum.

#### `set_availability(*, actor, schedule_id, rules, expected_revision) -> tuple[AvailabilityRuleInfo, ...]`

Replace the whole weekly grid of a schedule, with the schedule's revision as CAS.

- **Autorização:** alteração na agenda.
- **Erros:** NotFound; Forbidden; InvalidInput para faixa inválida, sobreposta ou com tipo de outro consultório; Conflict("stale_revision").
- **Efeitos:** exclusão lógica das faixas antigas, as novas gravadas e uma revisão nova da agenda.

#### `set_professional_active(*, actor, professional_id, active, expected_revision) -> ProfessionalInfo`

Deactivate (or reactivate) a professional, with CAS.

- **Autorização:** alteração no consultório.
- **Erros:** NotFound; Forbidden; Conflict("stale_revision"); Conflict("quota_exceeded") ao reativar acima do limite de profissionais do plano.
- **Efeitos:** grava a situação; um profissional inativo some das listas e não recebe agenda nova.

#### `set_schedule_access(*, actor, schedule_id, writer_group_ids, reader_group_ids, writer_user_ids=(), expected_revision) -> ScheduleInfo`

Share a schedule and its calendar, together, with exactly these groups and people, with CAS.

- **Autorização:** a capacidade ``access.manage``.
- **Erros:** Forbidden; NotFound; InvalidInput; Conflict("stale_revision").
- **Efeitos:** revoga nas duas o que saiu e concede o que entrou; vale na requisição seguinte.

#### `setup(*, actor, practice_name, timezone='America/Sao_Paulo', reader_group_ids=(), manager_group_ids=(), idempotency_key) -> PracticeInfo`

Create the default practice of the organization and share it with groups.

- **Autorização:** a capacidade ``access.manage`` e ``create`` em med_scheduling.practice.
- **Erros:** Forbidden; InvalidInput para nome vazio, fuso desconhecido, chave inválida ou mais de 20 grupos; Conflict("already_set_up") com um consultório padrão criado por outra chave.
- **Efeitos:** cria o consultório (privado, dono o ator), dá ao papel ``member`` leitura das tabelas do consultório e das agendas, concede leitura aos grupos de leitura e leitura e alteração aos de gestão. A mesma chave do mesmo ator devolve o já criado.

#### `start(*, actor, appointment_id, expected_revision) -> AppointmentInfo`

Start the care of an arrived patient, with CAS.

- **Autorização:** alteração na agenda.
- **Erros:** NotFound; Forbidden; Conflict("stale_revision", "invalid_transition").
- **Efeitos:** grava a situação e a hora e publica ``med_scheduling.appointment_started``.

#### `update_appointment_type(*, actor, type_id, changes, expected_revision) -> AppointmentTypeInfo`

Change a kind of appointment, with CAS; the code never changes.

- **Autorização:** alteração no consultório.
- **Erros:** NotFound; Forbidden; InvalidInput; Conflict("stale_revision").
- **Efeitos:** grava só os campos que mudaram; consultas já marcadas guardam a cópia do código de cobrança.

#### `update_practice(*, actor, changes, expected_revision) -> PracticeInfo`

Change the establishment data or the time zone of the practice, with CAS.

- **Autorização:** alteração no consultório.
- **Erros:** NotFound; Forbidden; InvalidInput com o nome do campo; Conflict("stale_revision").
- **Efeitos:** grava só os campos que mudaram.

#### `update_professional(*, actor, professional_id, changes, expected_revision) -> ProfessionalInfo`

Change the data of a professional, with CAS; the linked person never changes.

- **Autorização:** alteração no consultório.
- **Erros:** NotFound; Forbidden; InvalidInput; Conflict("stale_revision").
- **Efeitos:** grava só os campos que mudaram.

#### `update_room(*, actor, room_id, changes, expected_revision) -> RoomInfo`

Rename, change the kind or (de)activate a room, with CAS.

- **Autorização:** alteração no consultório.
- **Erros:** NotFound; Forbidden; InvalidInput; Conflict("stale_revision").
- **Efeitos:** grava só os campos que mudaram.

#### `update_schedule(*, actor, schedule_id, changes, expected_revision) -> ScheduleInfo`

Rename a schedule, change its slot, booking horizon or activity, with CAS.

- **Autorização:** alteração na agenda.
- **Erros:** NotFound; Forbidden; InvalidInput; Conflict("stale_revision").
- **Efeitos:** grava só os campos que mudaram.

#### `waitlist(*, actor, status='waiting', cursor=None, page_size=50) -> Page[WaitlistInfo]`

The waitlist of the practice, high priority first, then the oldest.

- **Autorização:** leitura do consultório.
- **Erros:** NotFound sem consultório; InvalidInput para situação, cursor ou página inválidos.
- **Efeitos:** nenhum.

#### `waitlist_candidates(*, actor, schedule_id, starts_at, ends_at) -> tuple[WaitlistInfo, ...]`

Waiting patients that fit a free time of a schedule: type, schedule, period and dates.

- **Autorização:** leitura da agenda e do consultório.
- **Erros:** NotFound; InvalidInput para horário sem fuso ou invertido.
- **Efeitos:** nenhum.

## DTOs

### `AppointmentAction`

A button on an appointment; ``url_name`` receives ``org`` and ``appointment_id``.

| Campo | Tipo |
|---|---|
| `code` | `str` |
| `label` | `Any` |
| `url_name` | `str` |
| `statuses` | `tuple[str, ...]` |
| `order` | `int` |

### `AppointmentActionInfo`

| Campo | Tipo |
|---|---|
| `code` | `str` |
| `label` | `str` |
| `url_name` | `str` |
| `order` | `int` |

### `AppointmentDetail`

One appointment with the notes and the history of its state.

| Campo | Tipo |
|---|---|
| `appointment` | `AppointmentInfo` |
| `notes` | `str` |
| `confirmed_at` | `datetime | None` |
| `arrived_at` | `datetime | None` |
| `started_at` | `datetime | None` |
| `completed_at` | `datetime | None` |
| `cancelled_at` | `datetime | None` |
| `cancel_reason` | `str` |
| `cancel_note` | `str` |
| `writable` | `bool` |

### `AppointmentInfo`

An appointment as lists show it: never the notes of the reception.

| Campo | Tipo |
|---|---|
| `sysid` | `UUID` |
| `code` | `str` |
| `schedule_id` | `UUID` |
| `patient_id` | `UUID` |
| `appointment_type_id` | `UUID` |
| `professional_id` | `UUID | None` |
| `room_id` | `UUID | None` |
| `starts_at` | `datetime` |
| `ends_at` | `datetime` |
| `status` | `str` |
| `is_fit_in` | `bool` |
| `billing_code` | `str` |
| `payment_kind` | `str` |
| `rescheduled_from_id` | `UUID | None` |
| `revision` | `int` |

### `AppointmentTypeInfo`

| Campo | Tipo |
|---|---|
| `sysid` | `UUID` |
| `practice_id` | `UUID` |
| `code` | `str` |
| `name` | `str` |
| `duration_minutes` | `int` |
| `color` | `str` |
| `billing_code` | `str` |
| `requires_room` | `bool` |
| `is_active` | `bool` |
| `revision` | `int` |

### `AvailabilityRuleInfo`

| Campo | Tipo |
|---|---|
| `sysid` | `UUID` |
| `schedule_id` | `UUID` |
| `weekday` | `int` |
| `start_minute` | `int` |
| `end_minute` | `int` |
| `valid_from` | `date` |
| `valid_until` | `date | None` |
| `appointment_type_id` | `UUID | None` |

### `AvailabilityRuleInput`

A weekly window: ``weekday`` 0 (Monday) to 6, minutes of the day in the practice's time zone.

| Campo | Tipo |
|---|---|
| `weekday` | `int` |
| `start_minute` | `int` |
| `end_minute` | `int` |
| `valid_from` | `date` |
| `valid_until` | `date | None` |
| `appointment_type_id` | `UUID | None` |

### `BlockInfo`

| Campo | Tipo |
|---|---|
| `sysid` | `UUID` |
| `schedule_id` | `UUID` |
| `starts_at` | `datetime` |
| `ends_at` | `datetime` |
| `reason` | `str` |
| `note` | `str` |
| `revision` | `int` |

### `DayAgenda`

| Campo | Tipo |
|---|---|
| `schedule` | `ScheduleInfo` |
| `appointments` | `tuple[AppointmentInfo, ...]` |
| `free` | `tuple[Slot, ...]` |

### `PracticeInfo`

| Campo | Tipo |
|---|---|
| `sysid` | `UUID` |
| `name` | `str` |
| `legal_name` | `str` |
| `tax_id` | `str` |
| `phone` | `str` |
| `email` | `str` |
| `address` | `str` |
| `city` | `str` |
| `state` | `str` |
| `timezone` | `str` |
| `revision` | `int` |
| `writable` | `bool` |

### `ProfessionalInfo`

| Campo | Tipo |
|---|---|
| `sysid` | `UUID` |
| `practice_id` | `UUID` |
| `user_id` | `UUID | None` |
| `display_name` | `str` |
| `council` | `str` |
| `council_number` | `str` |
| `council_state` | `str` |
| `council_label` | `str` |
| `specialty` | `str` |
| `rqe` | `str` |
| `tax_id` | `str` |
| `is_active` | `bool` |
| `revision` | `int` |

### `RoomInfo`

| Campo | Tipo |
|---|---|
| `sysid` | `UUID` |
| `practice_id` | `UUID` |
| `name` | `str` |
| `kind` | `str` |
| `is_active` | `bool` |
| `revision` | `int` |

### `ScheduleInfo`

| Campo | Tipo |
|---|---|
| `sysid` | `UUID` |
| `practice_id` | `UUID` |
| `name` | `str` |
| `professional_id` | `UUID | None` |
| `room_id` | `UUID | None` |
| `calendar_id` | `UUID` |
| `slot_minutes` | `int` |
| `booking_horizon_days` | `int` |
| `is_active` | `bool` |
| `revision` | `int` |
| `writable` | `bool` |

### `Slot`

| Campo | Tipo |
|---|---|
| `starts_at` | `datetime` |
| `ends_at` | `datetime` |
| `schedule_id` | `UUID` |

### `WaitlistInfo`

| Campo | Tipo |
|---|---|
| `sysid` | `UUID` |
| `patient_id` | `UUID` |
| `appointment_type_id` | `UUID | None` |
| `schedule_id` | `UUID | None` |
| `preferred_period` | `str` |
| `earliest_date` | `date` |
| `latest_date` | `date | None` |
| `priority` | `str` |
| `status` | `str` |
| `note` | `str` |
| `booked_appointment_id` | `UUID | None` |
| `created_at` | `datetime` |
| `revision` | `int` |

<!-- END GENERATED -->

## Eventos publicados

Payload: `code`, `schedule`, `patient` (o `sysid`, em texto), `appointment_type`, `billing_code`, `starts_at`, `ends_at` (ISO 8601, UTC) e `status`. Nunca nome do paciente nem observação.

| Tipo | Quando |
|---|---|
| `med_scheduling.appointment_booked` | `book`, e a consulta nova de uma remarcação para outra agenda |
| `med_scheduling.appointment_rescheduled` | `reschedule` na mesma agenda |
| `med_scheduling.appointment_cancelled` | `cancel`, e a consulta antiga de uma remarcação para outra agenda |
| `med_scheduling.appointment_confirmed`, `_arrived`, `_started`, `_completed`, `_no_show` | `confirm`, `check_in`, `start`, `complete`, `mark_no_show` |

## Pontos de extensão

`register_appointment_action(AppointmentAction(code, label, url_name, statuses, order))`, reexportada por este módulo e chamada no `ready()` da app que se pluga: um botão nas consultas nas situações `statuses`. O código é `<app_label>.<nome>` da própria app; a rota recebe `org` e `appointment_id` e autoriza sozinha.

## Notificações

`med_scheduling.patient_arrived`: ao profissional da agenda, na chegada do paciente; payload `code` e `starts_at`.

## Contribuições à página do paciente

Registradas no `ready()` pelos pontos de extensão de `med_patients`: aba `med_scheduling.appointments`, provider de linha do tempo e de relatório do titular com o mesmo código, e o passo de configuração `med_scheduling.practice`.

## API REST

As rotas de `/api/v1/o/<org>/apps/med_scheduling/` estão em `docs/spec.md` (seção "API REST"); cada uma chama um método desta classe.

## Histórico de versões
| Versão | Mudança |
|---|---|
| 0.1.0 | Primeira versão |
