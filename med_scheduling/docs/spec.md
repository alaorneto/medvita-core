# Agenda médica

A agenda do consultório: configuração (profissionais, salas, tipos de atendimento), grade de horários, bloqueios, consultas com situação, encaixe, lista de espera e recepção. As consultas são projetadas no `skeleton_calendar`. A app não guarda dado clínico nem valor: só um `billing_code` opaco que o financeiro resolve.

## Contract

### Ativação e dependências

Depende de `io.katua.sk.med.patients` (o paciente de cada consulta) e de `org.skeleton.calendar` (a projeção das consultas e a disponibilidade dos profissionais). Instalada globalmente e ativada por organização, depois das dependências.

### Acesso

Dois contêineres (`SecuredRecord` expostos):

- `Practice`: o consultório. Profissionais, salas, tipos de atendimento e a lista de espera são derivados dele: ler pede `read` no consultório, alterar pede `update`.
- `Schedule`: a agenda de um profissional, sala ou equipamento. Grade, bloqueios e consultas são derivados dela.

O `setup` (capacidade `access.manage`) cria o consultório padrão, privado e do administrador, dá ao papel `member` leitura e alteração das tabelas dos contêineres e concede leitura do consultório aos grupos de leitura e leitura e alteração aos de gestão. Pelo gateway genérico do núcleo o consultório só tem os dados do estabelecimento alterados.

### Modelo de dados

"P" marca os campos em `personal_fields`.

**`Practice`** (contêiner): `name` (obrigatório), `legal_name`, `tax_id` (CPF ou CNPJ válido), `phone`, `email`, `address`, `city`, `state`, `timezone` (nome IANA; padrão `America/Sao_Paulo`), `is_default` (um por organização).

**`Professional`** (derivada do consultório)

| Campo | P | Regra |
|---|---|---|
| `practice` | | imutável |
| `user` | | pessoa da organização ligada ao profissional (opcional); uma ficha viva por pessoa |
| `display_name` | P | obrigatório |
| `council`, `council_number`, `council_state` | P (número) | conselho (`crm`, `cro`, `crp`, `coren`, `crefito`, `crn`, `crfa`, `other`), número e UF; `council_label` é "CRM-SP 123456" |
| `specialty`, `rqe` | | especialidade e registro de qualificação |
| `tax_id` | P | CPF, para o recibo |
| `is_active` | | inativo some das listas |

**`Room`** (derivada do consultório): `name`, `kind` (`room`, `equipment`), `is_active`.

**`AppointmentType`** (derivada do consultório): `code` (minúsculas, único no consultório entre os vivos, imutável), `name`, `duration_minutes` (5 a 480), `color` (uma de oito chaves fixas, pintada pelo CSS da app), `billing_code`, `requires_room`, `is_active`.

**`Schedule`** (contêiner): `practice`, `name`, `professional` ou `room` (pelo menos um), `calendar` (o calendário compartilhado do `skeleton_calendar` que projeta a agenda; imutável), `slot_minutes` (5 a 120), `booking_horizon_days` (1 a 730), `is_active`, e os grupos e pessoas com que a agenda foi compartilhada (`writer_groups`, `reader_groups`, `writer_users`).

**`AvailabilityRule`** (derivada da agenda): `weekday` (0 = segunda a 6 = domingo), `start_minute` e `end_minute` (minutos do dia no fuso do consultório; fim depois do início), `valid_from`, `valid_until` (opcional), `appointment_type` (opcional: a faixa só aceita esse tipo). Faixas da mesma agenda não se sobrepõem no mesmo dia e período de validade.

**`ScheduleBlock`** (derivada da agenda): `starts_at`, `ends_at`, `reason` (`vacation`, `holiday`, `meeting`, `personal`, `other`), `note`.

### Agendas e o calendário do núcleo

- `create_schedule` (só com `access.manage`) cria, numa transação, o calendário compartilhado do núcleo (dono: a pessoa do profissional; numa agenda de sala, quem cria), a agenda e as concessões nas duas: grupos de escrita recebem leitura e alteração, de leitura só leitura, e as pessoas de escrita leitura e alteração.
- `set_schedule_access` é o único caminho para mudar o acesso de uma agenda: ele iguala as concessões da agenda e do calendário. Mudar só um lado pela tela de acesso do núcleo quebra a projeção.
- `set_availability` troca a grade inteira, com a revisão da agenda como CAS.
- Um bloqueio vira evento gerenciado no calendário (título "Bloqueio"); removê-lo remove o evento.
- O `setup` também dá ao papel `member` leitura e alteração da tabela de calendários do núcleo: quem tem concessão numa agenda precisa enxergar o calendário dela.

**`Appointment`** (derivada da agenda)

| Campo | Regra |
|---|---|
| `schedule`, `code`, `patient`, `rescheduled_from` | imutáveis; `code` é `A` + 7 dígitos da sequência `med_scheduling.appointment` |
| `appointment_type`, `professional`, `room` | o profissional é copiado da agenda na marcação; a sala é a pedida ou a da agenda |
| `starts_at`, `ends_at` | fim depois do início |
| `status` | `scheduled`, `confirmed`, `arrived`, `in_progress`, `completed`, `no_show`, `cancelled`; muda só pela máquina de `transitions.py` |
| `is_fit_in` | encaixe |
| `billing_code` | cópia do tipo na marcação |
| `payment_kind` | `private`, `insurance`, `courtesy` |
| `notes`, `cancel_note` | **sensíveis**: observação da recepção pode conter o motivo da consulta; nunca saem em lista nem em evento |
| `confirmed_at`, `arrived_at`, `started_at`, `completed_at`, `cancelled_at`, `cancel_reason` | carimbos e motivo |

A FK do paciente não é oculta: o banco e o núcleo impedem excluir um paciente com consulta.

### Consultas

- `book` trava a agenda (`SELECT ... FOR UPDATE`) enquanto confere o intervalo: duas marcações do mesmo horário nunca vencem ambas. Sem encaixe, o intervalo fica dentro da grade (do tipo, quando a faixa restringe), fora de bloqueio e sem cruzar consulta viva da agenda; com encaixe, dispensa a grade e a sobreposição, nunca o bloqueio. Um tipo que exige sala exige a sala, e a sala não pode ter outra consulta viva no intervalo, em qualquer agenda.
- O paciente precisa estar legível, ativo e sem tratamento restrito.
- O calendário da agenda recebe o evento gerenciado "<tipo> · <código>", com o profissional como participante: nunca nome, telefone ou observação do paciente.
- `reschedule` na mesma agenda muda o horário, mantém o código e volta a "agendada" se estava confirmada; para outra agenda, cancela a atual ("remarcada") e marca uma nova que aponta para ela.
- `cancel` vale para agendada, confirmada ou paciente chegou; remove o evento do calendário.
- `day` devolve, de cada agenda legível, as consultas e os horários livres do dia local, com um número fixo de consultas ao banco.
- Eventos `med_scheduling.appointment_*` com payload `code`, `schedule`, `patient`, `appointment_type`, `billing_code`, `starts_at`, `ends_at`, `status`.

### Atendimento

A máquina de situações (`transitions.py`) é a única fonte das mudanças:

```text
scheduled ──confirm──► confirmed ──check_in──► arrived ──start──► in_progress ──complete──► completed
    │  └───────────check_in────────────────────►┘          └────────────complete──────────►┘
    ├── mark_no_show ──► no_show       (de scheduled ou confirmed, só depois do início)
    └── cancel ──► cancelled           (de scheduled, confirmed ou arrived)
```

`completed`, `no_show` e `cancelled` são finais: erro de situação se corrige com outra consulta. Cada transição grava a hora, usa CAS e publica o evento dela. A chegada (`check_in`) notifica o profissional da agenda, uma vez por consulta; a notificação leva o código e o horário, nunca o paciente.

Outras apps põem botões na consulta com `register_appointment_action(AppointmentAction(code, label, url_name, statuses, order))`; `appointment_actions` devolve os das apps ativas para a situação atual, em ordem.

### Lista de espera

**`WaitlistEntry`** (derivada do consultório): `patient` (imutável), `appointment_type` e `schedule` (preferências opcionais), `preferred_period` (`any`, `morning`, `afternoon`, `evening`), `earliest_date`, `latest_date`, `priority` (`normal`, `high`), `status` (`waiting`, `booked`, `cancelled`, `expired`), `note` (**sensível**), `booked_appointment`.

- Incluir, cancelar e marcar a partir da lista exigem alteração no consultório: a lista é do grupo de gestão do consultório (em geral, a recepção).
- `waitlist_candidates` devolve as entradas aguardando que cabem num horário livre (agenda preferida, período do dia, datas, duração do tipo), alta prioridade primeiro, depois a mais antiga. Ninguém é marcado sozinho: a recepção escolhe.
- `book_from_waitlist` marca a consulta e muda a entrada para "agendado" na mesma transação; com o horário ocupado, a entrada continua aguardando.
- O job diário `med_scheduling.expire_waitlist` (uma organização por job) marca como expiradas as entradas com a última data vencida; repetir não muda nada.

### Horários livres

`available_slots(schedule_id, start_date, end_date, appointment_type_id=None)` devolve os horários livres de até 62 dias (`slots.py`, funções puras):

1. As faixas válidas do dia da semana (e do tipo pedido, quando a faixa restringe a um tipo) viram janelas no relógio local do consultório.
2. Cada janela é cortada em horários de `slot_minutes`; um horário serve se a duração (a do tipo pedido, ou o intervalo da agenda) termina dentro da janela.
3. Saem os horários que cruzam um bloqueio, uma consulta viva da agenda ou um compromisso do profissional no calendário do núcleo (`free_busy` com os eventos de que ele participa).
4. Saem os que já passaram e os além de `booking_horizon_days`.
5. Horário de verão: o horário gerado é do relógio local; um horário que não existe (o relógio pula) é descartado, e um ambíguo (o relógio volta) usa a primeira ocorrência.

### Páginas

Em `/o/<org>/apps/med_scheduling/` (nomes `med_scheduling:<nome>`); toda leitura e escrita passa pelo `SchedulingService` e pelo `PatientService`, e as horas aparecem no relógio do consultório.

| Nome | Página |
|---|---|
| `day` | Agenda do dia: uma coluna por agenda legível, consultas com a situação e os horários livres |
| `week` | Semana de uma agenda |
| `book` | Marcar: busca de paciente, agenda, tipo, dia, horário livre ou encaixe, pagamento e observação |
| `appointment` | Consulta: dados, situação, mudanças permitidas, ações de outras apps, remarcar e cancelar |
| `reception` | Recepção do dia: aguardando, em atendimento e próximos; atualiza a cada minuto sem script |
| `waitlist` | Lista de espera: entradas, incluir e tirar |
| `settings` | Dados do consultório, profissionais, salas e tipos |
| `schedules`, `schedule` | Agendas, grade semanal e bloqueios |
| `setup` | Configuração inicial (administradores) |
| `patient_section` | Aba "Consultas" da página do paciente |

Agenda ou consulta que o ator não lê responde 404. Quem lê a agenda e não lê o paciente vê "Paciente não disponível". A cor do tipo é uma classe do CSS da app, nunca `style=`.

### Integração com a página do paciente

No `ready()`: a aba "Consultas" (`register_patient_section`, ordem 20), a linha do tempo ("Consulta agendada", "Consulta realizada", "Falta", "Consulta cancelada", sem observação), o relatório do titular (data, código e situação de cada consulta legível) e o passo "Agenda médica" da lista de configuração. Cada contribuição só mostra consultas de agendas que o ator lê.

### API REST

Em `/api/v1/o/<org>/apps/med_scheduling/`:

| Método e caminho | O que faz | Token |
|---|---|---|
| `GET schedules/` | Agendas legíveis (`ScheduleInfo`) | `scheduling:read` |
| `GET schedules/<id>/slots/?start=&end=&type=` | Horários livres (`Slot`), datas `AAAA-MM-DD`, até 62 dias | `scheduling:read` |
| `GET appointments/?schedule=&patient=&start=&end=&status=&cursor=&page_size=` | Consultas (`AppointmentInfo`, sem observação) | `scheduling:read` |
| `POST appointments/` | Marca; exige `Idempotency-Key`; campos `schedule`, `patient`, `appointment_type`, `starts_at` (ISO 8601 com fuso) e opcionais `duration_minutes`, `fit_in`, `notes`, `payment_kind`, `room`; devolve 201 com `ETag` | `scheduling:write` |
| `GET appointments/<id>/` | Detalhe (`AppointmentDetail`, com a observação), com `ETag` | `scheduling:read` |
| `POST appointments/<id>/<mudança>/` | `confirm`, `check-in`, `start`, `complete`, `no-show`, `cancel` (`reason`, `note`) e `reschedule` (`starts_at`, `schedule`); exigem `If-Match` com a revisão | `scheduling:write` |

Toda rota aceita a sessão do navegador e o token de um cliente fora dele (o access token OIDC de um cliente nativo, como o Medvita Desktop, ou um token `skt_`) nos métodos da coluna "Token", com as mesmas respostas, filtros, `ETag`, `If-Match` e `Idempotency-Key` da sessão. O escopo só restringe: o serviço autoriza o papel da pessoa como para a sessão, e um token com o escopo continua sem ver o que o papel não alcança. O token amplo (`openid profile email`) leva todos os escopos; um cliente que o operador limitou (`native_client register --scope`) precisa do escopo da coluna e do escopo de tabela do contêiner que o serviço autoriza (`med_scheduling.practice:read` e `med_scheduling.schedule:read`, e as ações de escrita da agenda para marcar). Sem o escopo, a resposta é 403 `permission_denied` ("O token não tem o escopo exigido."); método fora da coluna é 403 `token_not_allowed`. Cada operação aparece no `/api/v1/openapi.json` só para quem pode chamá-la.

Campo fora da lista é 400; sem revisão é 400; revisão vencida é 409; agenda sem acesso ou de outra organização é 404. Sem exclusão pela API.

## Acceptance

- Só o administrador configura o consultório; a configuração é idempotente pela chave e única por organização.
- A recepção lê profissionais, salas e tipos e não os altera; a organização B não vê nada da A.
- Nome, número do conselho e CPF do profissional saem `[REDACTED]` na auditoria.
- Um grupo removido por `set_schedule_access` perde o acesso à agenda e ao calendário dela.
- Com o `skeleton_calendar` desativado, a agenda médica fica indisponível.
- Pelas páginas, a recepção marca, registra a chegada, remarca e cancela; revisão vencida mostra a mensagem de conflito.
- O título do evento no calendário nunca leva o nome do paciente; quem lê a agenda e não o paciente vê só o código.
- A agenda do dia faz o mesmo número de consultas ao banco com 1 ou 7 consultas.
- A API nunca devolve a observação numa lista e recusa campos de sistema.
