# med_scheduling: Agenda médica

Regras do núcleo: `AGENTS.md` do Skeleton (link no [`AGENTS.md` da raiz](../AGENTS.md)). Regras da suíte: [`../AGENTS.md`](../AGENTS.md). Este arquivo só traz o que é próprio desta app.

## Propósito e limites

Configuração do consultório (profissionais, salas, tipos de atendimento), grade de horários com períodos de hora marcada e de ordem de chegada, bloqueios, consultas com situação, encaixe, fila de chegada, lista de espera e recepção. Projeta as consultas no `skeleton_calendar`.

**Não faz:** dado clínico, valores (só guarda o `billing_code` opaco que o financeiro resolve), agendamento online pelo paciente, lembretes.

## Tabelas

- Contêineres `Practice` (o consultório e a configuração) e `Schedule` (a agenda de um profissional, sala ou equipamento).
- Derivadas do consultório: `Professional`, `Room`, `AppointmentType`, `WaitlistEntry`. Da agenda: `AvailabilityRule`, `ScheduleBlock`, `ScheduleAppointmentType`, `Appointment`. De `AvailabilityRule`, a dois saltos da agenda: `AvailabilityRuleType`.
- Nome, conselho e CPF do profissional são `personal_fields`; observações da consulta e da lista de espera e a marca de prioridade da consulta são `sensitive_fields`.

## Serviços e pontos de extensão

- Oferece `SchedulingService` e o registry `register_appointment_action`.
- Publica `appointment_booked`, `_rescheduled`, `_confirmed`, `_arrived`, `_started`, `_completed`, `_no_show` e `_cancelled`.
- Consome `PatientService` e o `CalendarService` do núcleo.
- Contribui para a página do paciente (aba, linha do tempo, relatório do titular) e para a lista de configuração, em `integration.py`.
- Superfícies: páginas em `views.py` e API REST em `api.py`; nenhuma consulta modelo, só os serviços.

## Invariantes do domínio

1. A situação da consulta só muda pela máquina de `transitions.py`; `completed`, `no_show` e `cancelled` são finais.
2. Duas consultas ativas não se sobrepõem na mesma agenda, salvo encaixe; a marcação trava a agenda.
3. O evento projetado no calendário nunca leva nome, telefone ou observação do paciente.
4. O acesso de uma agenda e o do calendário dela mudam juntos, só por `set_schedule_access`.
5. A observação da recepção só sai no detalhe de uma consulta; nunca em lista, evento, notificação, linha do tempo ou log.
6. A lista de espera é do grupo de gestão do consultório; ninguém é marcado a partir dela sem decisão da recepção.
7. A agenda sem linha em `ScheduleAppointmentType` atende todos os tipos ativos; com linhas, só os listados. Toda marcação passa por essa conferência (`_type_duration`), inclusive encaixe, lista de espera e remarcação para outra agenda.
8. A duração de uma marcação é a informada, depois a da agenda para o tipo, depois a do tipo. A consulta guarda a cópia da forma de pagamento e do código de cobrança do tipo: mudar o tipo não muda consulta marcada.
9. Grade e tipos da agenda usam a revisão da agenda como CAS; quem troca um deles dá revisão nova à agenda.
10. O período sem linha em `AvailabilityRuleType` (e sem o `appointment_type` antigo, que só é lido) atende todos os tipos da agenda; com linhas, só os listados. O encaixe dispensa a lista do período, nunca a da agenda.
11. `set_availability` compara a grade com a existente: o período que continua mantém a linha, e os tipos de um período são excluídos antes dele (a rota de acesso passa pelo período vivo). Os tipos dos períodos são lidos em lote.
12. O modo é do período e a marcação o diz (`mode`): hora num período de ordem de chegada, ou o contrário, é `mode_mismatch`. As regras puras estão em `slots.py` (hora marcada), `plan.py` (períodos do dia, sessão, lotação) e `queue.py` (ordem de chamada).
13. A consulta de ordem de chegada não tem hora: `starts_at` e `ends_at` são os limites do período, e agenda mais início do período identificam a sessão. Nenhuma conferência de sobreposição vale dentro da sessão; a lotação (vagas, ou minutos abertos) vale, salvo encaixe; bloqueio nunca é dispensado.
14. O número de chegada é dado só na chegada, com a agenda travada, e nunca é repetido nem reaproveitado na sessão. Toda operação que trava agenda e consulta trava a agenda antes.
15. A marca de prioridade (`is_priority`) só sai em `QueueEntry` e `AppointmentDetail`; nunca em `AppointmentInfo`, evento, notificação, calendário, linha do tempo ou log.
16. A consulta de ordem de chegada não tem evento próprio no calendário: a sessão tem um, "Ordem de chegada · N pacientes", refeito a cada marcação, remarcação e cancelamento.
17. O único JavaScript da app é `static/med_scheduling/med_scheduling.js`, opcional e ligado por `data-*`: nenhuma página depende dele.

## Testes e especificação

- Testes: `python -m pytest med_scheduling/tests -q -n auto` a partir da raiz, com o ambiente de `docs/development.md`.
- Especificação: `docs/spec.md`, decisões em `docs/adr.md` e contrato do serviço em `docs/service-api.md`, todos neste pacote.
