# med_scheduling: Agenda médica

Regras do núcleo: `AGENTS.md` do Skeleton (link no [`AGENTS.md` da raiz](../AGENTS.md)). Regras da suíte: [`../AGENTS.md`](../AGENTS.md). Este arquivo só traz o que é próprio desta app.

## Propósito e limites

Configuração do consultório (profissionais, salas, tipos de atendimento), grade de horários, bloqueios, consultas com situação, encaixe, lista de espera e recepção. Projeta as consultas no `skeleton_calendar`.

**Não faz:** dado clínico, valores (só guarda o `billing_code` opaco que o financeiro resolve), agendamento online pelo paciente, lembretes.

## Tabelas

- Contêineres `Practice` (o consultório e a configuração) e `Schedule` (a agenda de um profissional, sala ou equipamento).
- Derivadas do consultório: `Professional`, `Room`, `AppointmentType`, `WaitlistEntry`. Da agenda: `AvailabilityRule`, `ScheduleBlock`, `Appointment`.
- Nome, conselho e CPF do profissional são `personal_fields`; observações da consulta e da lista de espera são `sensitive_fields`.

## Serviços e pontos de extensão

- Oferece `SchedulingService` e o registry `register_appointment_action`.
- Publica `appointment_booked`, `_rescheduled`, `_confirmed`, `_arrived`, `_started`, `_completed`, `_no_show` e `_cancelled`.
- Consome `PatientService` e o `CalendarService` do núcleo.

## Invariantes do domínio

1. A situação da consulta só muda pela máquina de `transitions.py`; `completed`, `no_show` e `cancelled` são finais.
2. Duas consultas ativas não se sobrepõem na mesma agenda, salvo encaixe; a marcação trava a agenda.
3. O evento projetado no calendário nunca leva nome, telefone ou observação do paciente.
4. O acesso de uma agenda e o do calendário dela mudam juntos, só por `set_schedule_access`.

## Testes e especificação

- Testes: `python -m pytest med_scheduling/tests -q -n auto` a partir da raiz, com o ambiente de `docs/development.md`.
- Especificação: `docs/spec.md`, decisões em `docs/adr.md` e contrato do serviço em `docs/service-api.md`, todos neste pacote.
