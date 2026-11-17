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

#### `appointment_types(*, actor, active_only=True) -> tuple[AppointmentTypeInfo, ...]`

Kinds of appointment of the practice.

- **Autorização:** leitura do consultório.
- **Erros:** NotFound sem consultório legível.
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

#### `create_schedule(*, actor, name, professional_id=None, room_id=None, slot_minutes=30, writer_group_ids=(), reader_group_ids=(), writer_user_ids=(), idempotency_key) -> ScheduleInfo`

Create the schedule of a professional or room, with its shared calendar and the same access.

- **Autorização:** a capacidade ``access.manage`` e ``create`` em med_scheduling.schedule.
- **Erros:** Forbidden; NotFound para profissional ou sala ilegível; InvalidInput para nome vazio, sem profissional nem sala, intervalo fora de 5 a 120 minutos, mais de 20 grupos ou pessoas; Unavailable com a agenda do núcleo desativada.
- **Efeitos:** cria o calendário compartilhado, a agenda e as concessões nas duas, na transação do chamador; a mesma chave do mesmo ator devolve a agenda já criada.

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
- **Erros:** NotFound sem consultório; Forbidden se só lê; InvalidInput com o nome do campo ou para pessoa que não é membro ativo; Conflict("integrity_conflict") para pessoa já ligada a outro profissional vivo.
- **Efeitos:** grava o profissional; a mesma chave do mesmo ator devolve o já criado.

#### `remove_block(*, actor, block_id, expected_revision) -> None`

Remove a block of a schedule, with CAS, and its calendar event.

- **Autorização:** alteração na agenda.
- **Erros:** NotFound; Forbidden; Conflict("stale_revision").
- **Efeitos:** exclusão lógica do bloqueio e do evento projetado.

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
- **Erros:** NotFound; Forbidden; Conflict("stale_revision").
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

## DTOs

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

<!-- END GENERATED -->

## Eventos publicados

Nenhum nesta versão.

## Histórico de versões
| Versão | Mudança |
|---|---|
| 0.1.0 | Primeira versão |
