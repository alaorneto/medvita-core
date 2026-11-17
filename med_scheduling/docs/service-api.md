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

#### `rooms(*, actor, active_only=True) -> tuple[RoomInfo, ...]`

Rooms and equipment of the practice.

- **Autorização:** leitura do consultório.
- **Erros:** NotFound sem consultório legível.
- **Efeitos:** nenhum.

#### `set_professional_active(*, actor, professional_id, active, expected_revision) -> ProfessionalInfo`

Deactivate (or reactivate) a professional, with CAS.

- **Autorização:** alteração no consultório.
- **Erros:** NotFound; Forbidden; Conflict("stale_revision").
- **Efeitos:** grava a situação; um profissional inativo some das listas e não recebe agenda nova.

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

<!-- END GENERATED -->

## Eventos publicados

Nenhum nesta versão.

## Histórico de versões
| Versão | Mudança |
|---|---|
| 0.1.0 | Primeira versão |
