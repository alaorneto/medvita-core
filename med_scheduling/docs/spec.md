# Agenda médica

A agenda do consultório: configuração (profissionais, salas, tipos de atendimento), grade de horários com períodos de hora marcada e de ordem de chegada, bloqueios, consultas com situação, encaixe, fila de chegada, lista de espera e recepção. As consultas são projetadas no `skeleton_calendar`. A app não guarda dado clínico nem valor: só um `billing_code` opaco que o financeiro resolve.

## Contract

### Ativação e dependências

Depende de `io.medvita.patients` (o paciente de cada consulta) e de `org.skeleton.calendar` (a projeção das consultas e a disponibilidade dos profissionais). Instalada globalmente e ativada por organização, depois das dependências.

### Acesso

Dois contêineres (`SecuredRecord` expostos):

- `Practice`: o consultório. Profissionais, salas, tipos de atendimento e a lista de espera são derivados dele: ler pede `read` no consultório, alterar pede `update`.
- `Schedule`: a agenda de um profissional, sala ou equipamento. Grade, bloqueios, tipos atendidos e consultas são derivados dela; os tipos de cada período da grade são derivados do período, a dois saltos da agenda.

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

**`AppointmentType`** (derivada do consultório): `code` (minúsculas, único no consultório entre os vivos, imutável), `name`, `duration_minutes` (5 a 480, a duração padrão), `payment_kind` (`private`, `insurance`, `courtesy`; padrão `private`), `color` (uma de oito chaves fixas, pintada pelo CSS da app), `billing_code`, `requires_room`, `is_active`. "Particular", "Unimed" e "Retorno Unimed" são tipos: o tipo diz como a consulta é paga e quanto dura; não há cadastro de convênios à parte.

**`Schedule`** (contêiner): `practice`, `name`, `professional` ou `room` (pelo menos um), `calendar` (o calendário compartilhado do `skeleton_calendar` que projeta a agenda; imutável), `slot_minutes` (5 a 120), `booking_horizon_days` (1 a 730), `is_active`, e os grupos e pessoas com que a agenda foi compartilhada (`writer_groups`, `reader_groups`, `writer_users`).

**`AvailabilityRule`** (derivada da agenda): um período da grade semanal. `weekday` (0 = segunda a 6 = domingo), `start_minute` e `end_minute` (minutos do dia no fuso do consultório; fim depois do início, até 1440), `valid_from`, `valid_until` (opcional). Períodos da mesma agenda não se sobrepõem no mesmo dia e período de validade, e uma agenda tem até 100. `appointment_type` é a forma antiga de restringir o período a um tipo só: continua lida e não é mais escrita. `mode` é `booked` (hora marcada, o padrão) ou `walk_in` (ordem de chegada); `capacity` são as vagas de um período de ordem de chegada (1 a 500, opcional; o banco recusa vagas em hora marcada). `on_date` (imutável) é vazio no período da grade semanal e traz o dia no período de um **dia alterado** (a exceção daquele dia): nele `weekday` é o dia da semana da data e a validade começa e termina nela, o que o banco confere. Um dia com período próprio segue só os períodos dele; a grade semanal não vale naquele dia.

**`AvailabilityRuleType`** (derivada do período; tabela `med_scheduling_rule_type`): `rule` e `appointment_type` (imutáveis; uma linha viva por período e tipo). São os tipos que o período atende. Um período sem nenhuma linha (e sem o `appointment_type` antigo) atende todos os tipos que a agenda atende. O acesso segue a agenda pelo período: com o período excluído, as linhas dele deixam de ser alcançadas.

**`ScheduleBlock`** (derivada da agenda): `starts_at`, `ends_at`, `reason` (`vacation`, `holiday`, `meeting`, `personal`, `other`), `note`.

**`ScheduleAppointmentType`** (derivada da agenda; tabela `med_scheduling_schedule_type`): `schedule` e `appointment_type` (imutáveis; uma linha viva por agenda e tipo), `duration_minutes` (opcional, 5 a 480: a duração do tipo nesta agenda; vazio vale a do tipo), `allow_booked` e `allow_walk_in` (os modos em que a agenda atende o tipo; pelo menos um). Uma agenda sem nenhuma linha atende todos os tipos ativos do consultório.

### Agendas e o calendário do núcleo

- `create_schedule` (só com `access.manage`) cria, numa transação, o calendário compartilhado do núcleo (dono: a pessoa do profissional; numa agenda de sala, quem cria), a agenda e as concessões nas duas: grupos de escrita recebem leitura e alteração, de leitura só leitura, e as pessoas de escrita leitura e alteração.
- `set_schedule_access` é o único caminho para mudar o acesso de uma agenda: ele iguala as concessões da agenda e do calendário. Mudar só um lado pela tela de acesso do núcleo quebra a projeção.
- `set_availability` faz a grade ser a lista recebida, com a revisão da agenda como CAS, comparando com o que existe: o período que continua (mesmo dia da semana, minutos e validade) mantém a linha, e nele só os tipos que mudaram são gravados; o que saiu é excluído logicamente, os tipos dele antes. Gravar a mesma grade não escreve nenhuma linha além da revisão nova da agenda. O modo e as vagas de um período que continua são alterados na própria linha; períodos de modos diferentes também não se sobrepõem. Cada período diz os tipos em `appointment_type_ids` (`appointment_type_id`, o nome antigo de um tipo só, entra no conjunto). Um tipo que **entra** num período tem de ser um que a agenda atende no modo do período (ativo, da organização e, na agenda configurada, escolhido com aquele modo); um tipo que já estava num período fica, mesmo que a agenda tenha deixado de atendê-lo, e trocar o modo do período confere todos os tipos dele. A linha antiga com `appointment_type` perde a coluna quando os tipos do período mudam. `availability` devolve cada período com `appointment_type_ids`, `mode` e `capacity`; `appointment_type_id` responde enquanto houver um tipo só. Mudar a grade não muda as consultas já marcadas, e por isso `set_availability` recusa, com `Conflict("plan_conflicts")`, a grade que troca o modo de um período sob consultas vivas de hoje em diante (a consulta com hora num período que viraria ordem de chegada, e a de ordem de chegada num período que viraria hora marcada); a mensagem diz o último dia afetado, e a mudança passa quando vale depois dele. O período que só sai da grade não é recusado: as consultas dele continuam como estão. `availability_conflicts(schedule_id, rules)` devolve essas consultas sem gravar nada. A grade semanal nunca toca nos dias alterados.
- **Dia alterado.** `set_day_exception(schedule_id, date, windows, expected_revision, convert_existing=False, expected_affected=None)` faz o dia seguir os períodos recebidos (`DayWindowInput`: minutos, modo, vagas e tipos, de 1 a 20, sem sobreposição) no lugar da grade semanal, com a revisão da agenda como CAS e a mesma comparação da grade (o período que continua mantém a linha). Zero períodos é recusado: fechar o dia é bloqueio. Dia que já passou é recusado. `clear_day_exception` devolve o dia à grade semanal, e `day_exceptions(schedule_id, start_date=None, end_date=None)` lista os dias alterados (de hoje em diante, sem as datas).
- **Conversão conferida.** Trocar os períodos de um dia (ou devolvê-lo à grade) confere as consultas vivas dele, menos as que estão em atendimento, as encerradas e os encaixes com hora. `plan_conflicts(schedule_id, date, windows=None)` devolve o que a troca faria com cada uma (`PlanConflict`), sem gravar; `windows=None` pergunta pela volta à grade semanal. Duas mudanças são **movimentos** que quem altera a agenda confirma: `to_walk_in` (a consulta tinha hora e o período dela vira ordem de chegada) e `to_session` (a de ordem de chegada cujo período muda de limites). Três **impedem** a troca: `outside` (nenhum período novo comporta a consulta), `to_booked` (ordem de chegada num período que viraria hora marcada) e `arrived` (o paciente já chegou: a fila mantém os números). Com impedimento, ou com movimento sem `convert_existing=True`, a troca responde `Conflict("plan_conflicts")` e nada muda. A confirmação leva em `expected_affected` os identificadores dos movimentos que a pessoa viu: se não forem exatamente os de agora (alguém marcou ou cancelou no meio), responde `Conflict("plan_changed")` e nada muda; marcar uma consulta não muda a revisão da agenda, por isso a lista é conferida à parte, com a agenda travada. Confirmada, cada consulta movida passa aos limites do período, fica `walk_in` sem número de chegada, mantém o código e a duração planejada, volta a "agendada" se estava confirmada, troca o evento próprio pelo da sessão e publica `appointment_rescheduled`. O movimento dispensa as vagas e os tipos do período de destino; `over_capacity` e `kind_not_listed` avisam quando isso acontece.
- `set_schedule_types` troca os tipos atendidos pela agenda, com a mesma revisão como CAS (salvar a grade e salvar os tipos a partir da mesma página não vencem os dois): a linha que continua é alterada no lugar, a que sai é excluída logicamente e a lista vazia devolve a agenda a "todos os tipos ativos". `schedule_types` devolve os tipos atendidos com a duração em vigor em cada um. As consultas já marcadas não mudam.
- Um bloqueio vira evento gerenciado no calendário (título "Bloqueio"); removê-lo remove o evento.
- O `setup` também dá ao papel `member` leitura e alteração da tabela de calendários do núcleo: quem tem concessão numa agenda precisa enxergar o calendário dela.

**`Appointment`** (derivada da agenda)

| Campo | Regra |
|---|---|
| `schedule`, `code`, `patient`, `rescheduled_from` | imutáveis; `code` é `A` + 7 dígitos da sequência `med_scheduling.appointment` |
| `appointment_type`, `professional`, `room` | o profissional é copiado da agenda na marcação; a sala é a pedida ou a da agenda |
| `starts_at`, `ends_at` | fim depois do início; na ordem de chegada são os limites do período, não uma hora da consulta |
| `mode` | `booked` (hora marcada) ou `walk_in` (ordem de chegada) |
| `duration_minutes` | a duração planejada (5 a 480); numa consulta anterior à coluna vale o intervalo |
| `arrival_number` | o número de chegada na sessão; só na ordem de chegada, único por agenda e início do período, nunca reaproveitado |
| `is_priority` | **sensível**: a marca de prioridade legal (Lei 10.048), sem o motivo |
| `status` | `scheduled`, `confirmed`, `arrived`, `in_progress`, `completed`, `no_show`, `cancelled`; muda só pela máquina de `transitions.py` |
| `is_fit_in` | encaixe |
| `billing_code` | cópia do tipo na marcação |
| `payment_kind` | `private`, `insurance`, `courtesy`: cópia do tipo na marcação, salvo valor explícito |
| `notes`, `cancel_note` | **sensíveis**: observação da recepção pode conter o motivo da consulta; nunca saem em lista nem em evento |
| `confirmed_at`, `arrived_at`, `started_at`, `completed_at`, `cancelled_at`, `cancel_reason` | carimbos e motivo |

A FK do paciente não é oculta: o banco e o núcleo impedem excluir um paciente com consulta.

### Consultas

- `book` trava a agenda (`SELECT ... FOR UPDATE`) enquanto confere o intervalo: duas marcações do mesmo horário nunca vencem ambas. Sem encaixe, o intervalo fica dentro de um período da grade que atende o tipo (o que não lista tipos atende todos), fora de bloqueio e sem cruzar consulta viva da agenda; com encaixe, dispensa a grade, os tipos do período e a sobreposição, nunca o bloqueio nem os tipos da agenda. Um tipo que exige sala exige a sala, e a sala não pode ter outra consulta viva no intervalo, em qualquer agenda.
- O paciente precisa estar legível, ativo e sem tratamento restrito.
- **Tipo aceito.** A marcação aceita o tipo quando ele está ativo e a agenda não escolheu tipos ou escolheu este com a hora marcada permitida; fora disso responde `Conflict("type_not_allowed")`, com encaixe ou sem.
- **Duração.** Vale a informada na marcação; sem ela, a da agenda para o tipo; sem ela, a do tipo. Sempre de 5 a 480 minutos.
- **Forma de pagamento.** A consulta nasce com a do tipo; um valor explícito na marcação vence. Mudar o tipo depois não muda as consultas marcadas, e a remarcação para outra agenda leva a forma de pagamento que a consulta tinha.
- O calendário da agenda recebe o evento gerenciado "<tipo> · <código>", com o profissional como participante: nunca nome, telefone ou observação do paciente.
- **Modo explícito.** `book(mode="booked")` marca com hora, num período de hora marcada; `book(mode="walk_in")` marca sem hora: `starts_at` é qualquer instante de um período de ordem de chegada, e a consulta fica com os limites do período e com a duração planejada. A hora dentro de um período de ordem de chegada, ou a marcação sem hora num período de hora marcada, responde `Conflict("mode_mismatch")`; fora de qualquer período, `slot_unavailable`. O encaixe com hora continua aceito em qualquer dia, inclusive dentro de um período de ordem de chegada.
- **Sessão.** A agenda e um período de ordem de chegada num dia formam a sessão: as consultas dela dividem o intervalo do período. A sessão comporta as vagas do período (`capacity`); sem vagas, a soma das durações planejadas não passa dos minutos abertos do período, que são os minutos dele menos o que os bloqueios da agenda tomam. Além disso responde `Conflict("session_full")`. Contam as consultas não canceladas que não são encaixe: cancelar libera a vaga, e o encaixe dispensa a lotação e os tipos do período, nunca o bloqueio (o período todo bloqueado responde `slot_unavailable`) nem os tipos da agenda.
- **Tipo na ordem de chegada.** O tipo precisa de `allow_walk_in` na agenda configurada e de estar na lista do período, quando ele lista tipos; fora disso responde `type_not_allowed`.
- **Sala.** As consultas de uma sessão não disputam a sala da agenda entre si, nem com um encaixe com hora da mesma agenda; continuam disputando com as consultas de outras agendas na mesma sala.
- **Calendário da sessão.** Uma consulta de ordem de chegada não tem evento próprio: a sessão tem um evento gerenciado "Ordem de chegada · N pacientes", com os limites do período e o profissional como participante, em que N conta as consultas não canceladas (a sessão não some do calendário enquanto os pacientes são atendidos). O evento nasce na primeira marcação e sai com a última cancelada. Chave `session:<agenda>:<AAAAMMDD>:<minuto>`, caminho `apps/med_scheduling/schedules/<id>/queue/<data>/`.
- `reschedule` na mesma agenda muda o horário, mantém o código e volta a "agendada" se estava confirmada; para outra agenda, cancela a atual ("remarcada") e marca uma nova que aponta para ela, na sala da agenda de destino. Nos dois casos a consulta continua encaixe ou regular como era, e no modo em que estava; `fit_in` e `mode` explícitos mudam isso. Para a ordem de chegada, `starts_at` é um instante do período de destino, com as regras da sessão (a consulta não conta a si mesma na lotação), e a consulta mantém a duração planejada; o evento próprio dá lugar ao da sessão, e o contrário na volta à hora marcada. A consulta de ordem de chegada cujo paciente já chegou não é remarcada, e a de hora marcada que já chegou não entra numa sessão: a fila mantém os números. As agendas são travadas em ordem de identificador antes da consulta, a mesma ordem de toda operação que trava as duas.
- `cancel` vale para agendada, confirmada ou paciente chegou; remove o evento do calendário (na ordem de chegada, o evento da sessão passa a contar uma a menos). Trava a agenda antes da consulta, como toda operação que mexe numa sessão.
- `day` devolve, de cada agenda legível, as consultas, os horários livres (só de hora marcada) e as sessões de ordem de chegada do dia local com as filas, com um número fixo de consultas ao banco.
- `day_plan(schedule_id, start_date, end_date)` devolve os períodos efetivos de até 62 dias (`PeriodPlan`): modo, vagas, tipos, quantas consultas e minutos o período já tem, os minutos abertos e, na ordem de chegada, se está lotado; `is_exception` diz se o período é de um dia alterado.
- Eventos `med_scheduling.appointment_*` com payload `code`, `schedule`, `patient`, `appointment_type`, `billing_code`, `starts_at`, `ends_at`, `status`, `mode`. Numa consulta de ordem de chegada `starts_at` e `ends_at` são os limites do período: quem mostra a hora olha `mode`.

### Atendimento

A máquina de situações (`transitions.py`) é a única fonte das mudanças:

```text
scheduled ──confirm──► confirmed ──check_in──► arrived ──start──► in_progress ──complete──► completed
    │  └───────────check_in────────────────────►┘          └────────────complete──────────►┘
    ├── mark_no_show ──► no_show       (de scheduled ou confirmed, só depois do início;
    │                                   na ordem de chegada, só depois do fim do período)
    └── cancel ──► cancelled           (de scheduled, confirmed ou arrived)
```

`completed`, `no_show` e `cancelled` são finais: erro de situação se corrige com outra consulta. Cada transição grava a hora, usa CAS e publica o evento dela. A chegada (`check_in`) notifica o profissional da agenda, uma vez por consulta; a notificação leva o código e o horário, nunca o paciente.

**Fila da ordem de chegada.** Na chegada, a consulta de ordem de chegada recebe o próximo número da sessão, dado com a agenda travada (a agenda antes da consulta) e garantido por restrição única no banco; o número de uma cancelada não é dado de novo. `check_in(priority=True)` põe a marca de prioridade legal; `set_priority` a põe ou tira, com CAS, enquanto o atendimento não começou. `queue(schedule_id, date)` devolve as sessões do dia (`QueueSession`): quem aguarda, na ordem de chamada (prioritários primeiro, depois o número de chegada), os esperados (que ainda não chegaram, na ordem em que foram marcados), quem está em atendimento e quem já foi atendido ou faltou, com as vagas e a ocupação. Uma sessão cujo período saiu da grade continua aparecendo enquanto tiver consultas.

A marca de prioridade é dado sensível: sai só em `QueueEntry` (em `queue` e em `day`) e em `AppointmentDetail`, para quem lê a agenda; nunca em `AppointmentInfo`, em evento, na notificação da chegada ou no calendário, e fica `[REDACTED]` na auditoria. Pôr ou tirar a marca não publica evento.

Outras apps põem botões na consulta com `register_appointment_action(AppointmentAction(code, label, url_name, statuses, order))`; `appointment_actions` devolve os das apps ativas para a situação atual, em ordem.

### Lista de espera

**`WaitlistEntry`** (derivada do consultório): `patient` (imutável), `appointment_type` e `schedule` (preferências opcionais), `preferred_period` (`any`, `morning`, `afternoon`, `evening`), `earliest_date`, `latest_date`, `priority` (`normal`, `high`), `status` (`waiting`, `booked`, `cancelled`, `expired`), `note` (**sensível**), `booked_appointment`.

- Incluir, cancelar e marcar a partir da lista exigem alteração no consultório: a lista é do grupo de gestão do consultório (em geral, a recepção).
- `waitlist_candidates` devolve as entradas aguardando que cabem num horário livre (agenda preferida, período do dia, datas, duração do tipo), alta prioridade primeiro, depois a mais antiga. Ninguém é marcado sozinho: a recepção escolhe.
- `book_from_waitlist` marca a consulta do tipo da entrada (com a duração da agenda para o tipo, ou a informada em `duration_minutes`, e a forma de pagamento do tipo) e muda a entrada para "agendado" na mesma transação; com o horário ocupado, a sessão lotada ou o tipo não atendido pela agenda, a entrada continua aguardando. `mode="walk_in"` põe o paciente na sessão do período de ordem de chegada do horário.
- O job diário `med_scheduling.expire_waitlist` (uma organização por job) marca como expiradas as entradas com a última data vencida; repetir não muda nada.

### Horários livres

`available_slots(schedule_id, start_date, end_date, appointment_type_id=None, duration_minutes=None)` devolve os horários livres de até 62 dias (`slots.py`, funções puras). Um tipo que a agenda não atende com hora marcada não tem horário livre.

1. Os períodos de hora marcada válidos do dia da semana viram janelas no relógio local do consultório (o período de ordem de chegada não tem horário livre: `plan.py` cuida dele). O período que lista tipos só dá horário ao tipo pedido que esteja na lista; sem tipo pedido, só os períodos sem lista dão horário.
2. Cada janela é cortada em horários de `slot_minutes`; um horário serve se a duração (a informada; sem ela, a da agenda para o tipo pedido, depois a do tipo; sem tipo, o intervalo da agenda) termina dentro da janela.
3. Saem os horários que cruzam um bloqueio, uma consulta viva da agenda ou um compromisso do profissional no calendário do núcleo (`free_busy` com os eventos de que ele participa).
4. Saem os que já passaram e os além de `booking_horizon_days`.
5. Horário de verão: o horário gerado é do relógio local; um horário que não existe (o relógio pula) é descartado, e um ambíguo (o relógio volta) usa a primeira ocorrência.

A consulta viva sai da lista pela própria agenda, e não só pelo calendário do profissional: vale igual para a agenda de sala e para a do profissional sem pessoa ligada. `day` usa o mesmo cálculo com o intervalo da agenda como duração e mostra os horários livres de todos os períodos do dia, inclusive os que listam tipos. Cada `Slot` leva em `appointment_type_ids` os tipos do período em que está (vazio: todos os da agenda). Os tipos dos períodos são lidos numa consulta só para todas as agendas do dia: o número de consultas ao banco não cresce com o número de períodos.

### Páginas

Em `/o/<org>/apps/med_scheduling/` (nomes `med_scheduling:<nome>`); toda leitura e escrita passa pelo `SchedulingService` e pelo `PatientService`. As horas e o dia corrente são os do relógio do consultório: toda página roda com o fuso do consultório ativo (`practice_page`), qualquer que seja a preferência de fuso de quem lê, e a hora digitada num formulário é lida no mesmo relógio.

| Nome | Página |
|---|---|
| `day` | Agenda do dia: uma coluna por agenda legível, consultas com a situação, os horários livres e um cartão por período de ordem de chegada |
| `week` | Semana de uma agenda, com o cartão de cada período de ordem de chegada e a marca "Dia alterado" |
| `book` | Marcar: busca de paciente, agenda, tipo, dia, duração, os períodos do dia (horário livre, ou o período de ordem de chegada), encaixe, chegada, prioridade e observação |
| `appointment` | Consulta: dados, modo, situação, chegada e prioridade, mudanças permitidas, ações de outras apps, remarcar e cancelar |
| `check-in`, `priority` | Registrar a chegada (com ou sem prioridade) e corrigir a prioridade de uma consulta (só `POST`) |
| `reception` | Recepção do dia: aguardando, em atendimento e próximos das consultas com hora, e a fila de cada período de ordem de chegada; atualiza a cada minuto sem script |
| `queue` | Fila de uma agenda num dia (`schedules/<id>/queue/<AAAA-MM-DD>/`): os períodos de ordem de chegada com quem aguarda, quem é esperado e quem já foi atendido |
| `waitlist` | Lista de espera: entradas, incluir e tirar |
| `settings` | Dados do consultório, profissionais, salas e tipos (com a forma de pagamento) |
| `type-edit` | Alterar um tipo de atendimento: nome, duração, forma de pagamento, cor, código de cobrança, sala e ativo |
| `schedules`, `schedule` | Agendas; na agenda, a grade semanal, os dias alterados, os tipos atendidos e os bloqueios |
| `period-edit`, `period-remove` | Alterar um período da grade semanal; tirá-lo da grade (só `POST`) |
| `day-exception` | Alterar um dia de uma agenda (`schedules/<id>/day/?date=<AAAA-MM-DD>`): os períodos daquele dia, a conferência das consultas que mudam e a volta à grade semanal |
| `setup` | Configuração inicial (administradores) |
| `patient_section` | Aba "Consultas" da página do paciente |

Agenda ou consulta que o ator não lê responde 404. Quem lê a agenda e não lê o paciente vê "Paciente não disponível". A cor do tipo é uma classe do CSS da app, nunca `style=`.

**Marcar.** O seletor de tipo traz os tipos que a agenda escolhida atende, em qualquer modo, com a duração no rótulo ("Unimed · 20 min"). "Duração" vem preenchida com a sugestão e é editável; os horários livres são calculados com ela e a consulta é marcada com ela. A página funciona sem script: uma duração que ninguém digitou (vazia, ou ainda igual à sugestão anterior) acompanha o tipo quando ele muda, e uma duração digitada fica. A forma de pagamento aparece como texto e vem do tipo. Vindo da lista de espera, o tipo é o da entrada.

**Períodos do dia ao marcar.** Escolhidos a agenda e o dia, Marcar mostra "Períodos de <dia>", um cartão por período com o horário, o modo e a ocupação. O período de hora marcada lista os horários livres; o de ordem de chegada traz uma opção só, o próprio período ("9 de 15 vagas", ou "3 pacientes · 60 de 240 min" quando não tem vagas definidas). Horário e período ficam no mesmo grupo de escolha, e a marcação leva o modo do que foi escolhido. O período lotado leva a marca "Lotado" e o aviso de que só aceita encaixe, e o período que não lista o tipo escolhido diz o mesmo. O período que já terminou, o bloqueado por inteiro e o de um modo em que a agenda não atende o tipo não trazem opção e dizem por quê. Dia sem período mostra "Esta agenda não atende neste dia." com o atalho para a semana. Cada recusa do serviço aparece no campo a que se refere: `slot_unavailable`, `mode_mismatch`, `session_full` e `room_unavailable` no horário, `type_not_allowed` no tipo. "Encaixe" num período de ordem de chegada lotado inclui o paciente mesmo assim.

**Chegada e prioridade ao marcar.** "O paciente já está aqui: registrar a chegada agora" só aparece quando o dia é hoje: a página marca e registra a chegada num envio só, e volta à fila (ordem de chegada) ou à Recepção (hora marcada). "Atendimento prioritário (Lei 10.048)" grava a marca de prioridade. A prioridade nunca vai num endereço: é sempre campo de formulário enviado por `POST`.

**Fila.** A Recepção e a página `queue` mostram, por período de ordem de chegada, a tabela da fila na ordem de chamada (Chegada nº, paciente, prioridade, tipo, hora da chegada), "Em atendimento", "Esperados" e "Atendidos e faltas". Cada esperado tem dois botões, "Registrar chegada" e "Chegada prioritária (Lei 10.048)": são botões, e não uma caixa de seleção, porque a Recepção se recarrega a cada minuto e uma caixa marcada se perderia. "Chegou agora" (só hoje, com o período ainda aberto e para quem altera a agenda) leva a Marcar com o período escolhido e a chegada marcada, para quem aparece sem marcação. Enviar a chegada duas vezes dá o conflito de revisão vencida, e o número de chegada não muda. No Dia e na Semana o período aparece como um cartão com a ocupação e os pacientes, e leva à fila. A marca "Prioritário" só aparece na fila e na página da consulta.

**Consulta de ordem de chegada.** A página da consulta mostra o período no lugar da hora, o modo, a duração planejada, o número de chegada e a prioridade, com o botão que marca ou tira a prioridade (CAS pela revisão). Remarcar aceita trocar de modo: "Como está", ou o outro modo; na ordem de chegada a hora informada só escolhe o período em que ela cai. Depois da chegada a consulta de ordem de chegada não é remarcada.

**Tipos da agenda.** Na página da agenda, quem a lê vê os tipos atendidos e a duração de cada um; quem a altera escolhe entre "todos os tipos do consultório" e "só os marcados", com a duração própria opcional por tipo. "Só os marcados" sem nenhum marcado é erro do formulário. Cada tipo marcado diz também como a agenda o atende, "Hora marcada" e "Ordem de chegada" (os dois, por padrão); tipo marcado sem nenhum modo é erro no campo do tipo.

**Grade semanal.** A página da agenda mostra a semana inteira, uma coluna por dia e um cartão por período, com o horário, os tipos que o período atende ("Todos os tipos da agenda" quando não lista nenhum) e a validade quando ela começa no futuro ou tem fim; o dia sem período mostra "Sem atendimento". Um tipo que o período lista e a agenda deixou de atender aparece marcado. Quem altera a agenda tem, em cada cartão, "Editar" e "Remover", e o formulário "Adicionar períodos": os dias da semana em caixas de seleção, até três horários (início e fim; fim às 00:00 vale o fim do dia), o modo de atendimento, as vagas (só na ordem de chegada, opcionais), os tipos e a validade. Cada horário vira um período em cada dia marcado, e os períodos que já existem ficam como estão: um dia pode ter quantos períodos precisar. O cartão do período de ordem de chegada diz "Ordem de chegada · N vagas" ou "sem limite de vagas". Vagas num período de hora marcada, e um tipo que a agenda não atende no modo do período, são recusados no campo. A página de um período altera o dia, o horário, o modo, as vagas, os tipos e a validade dele; mudar só os tipos mantém o período, mudar o horário faz outro. O período que se sobrepõe a outro é recusado no campo do horário, dizendo o dia e o período com que cruza, e o que foi digitado fica no formulário. Remover um período não muda as consultas já marcadas nele.

**Alterar este dia.** Quem altera a agenda chega à página pelo Dia e pela Semana ("Alterar este dia", só de hoje em diante) e pela página da agenda (a lista "Dias alterados" e o campo de data). Ela mostra como o dia está (os períodos, o modo e a ocupação de cada um, e se o dia segue a grade ou já foi alterado) e o formulário "Períodos deste dia" já preenchido com eles: um quadro por período, com início, fim, modo, vagas e tipos, e ao menos dois quadros vazios; quadro sem horário não conta. "Trocar para ordem de chegada" reabre o formulário com todos os períodos nesse modo, sem gravar nada. Salvar grava direto quando nenhuma consulta muda. Quando muda, nada é gravado e a página mostra o segundo passo: "Confira as consultas que mudam", com o código, a hora atual e o que acontece com cada uma ("Passa para a ordem de chegada das 08:00–12:00."), os avisos "Além das vagas do período" e "O período não lista o tipo desta consulta", e o botão "Confirmar e mover N consultas", que reenvia os períodos digitados com a lista vista. Se a lista mudou no meio, a página a mostra de novo e pede outra conferência. As consultas que impedem a mudança aparecem em "Consultas que impedem a mudança", com o motivo, sem botão de confirmar e com o formulário como foi digitado. O nome do paciente só aparece para quem o lê; os outros veem "Paciente não disponível" e o código. "Voltar à grade semanal" aparece no dia alterado e passa pela mesma conferência. O dia que já passou é mostrado e não tem formulário. Depois de gravar, a página volta à agenda do dia. Erros do formulário aparecem no campo do quadro: sobreposição entre quadros, vagas em hora marcada, tipo que a agenda não atende no modo, nenhum período.

**Grade sob consultas marcadas.** Trocar o modo de um período da grade com consultas vivas nele é recusado com o último dia afetado. A página do período oferece então "Mudar a partir de <dia seguinte>": o período fica como está até a véspera (`valid_until`) e o período novo vale dali em diante. Para mudar um dia antes disso, a pessoa usa "Alterar este dia".

**Script opcional.** `static/med_scheduling/med_scheduling.js` é o único script da app, carregado por `<script src>` com `defer` nas páginas `book`, `schedule`, `period-edit` e `day-exception` e ligado por atributos `data-*`. Em Marcar, a duração que ninguém digitou acompanha o tipo assim que ele é trocado, como o botão de atualizar faz no servidor. Na grade, os horários depois do primeiro ficam recolhidos enquanto vazios, atrás de "Adicionar outro horário", e "Vagas" fica recolhido enquanto o modo não é ordem de chegada (em Alterar este dia, quadro a quadro, e os quadros vazios ficam atrás de "Adicionar outro período"). Sem o script as páginas mostram tudo e funcionam igual; nenhuma página tem script em linha, `style=` ou atributo `on*=`.

**Revisão vencida.** Ao salvar um tipo, os tipos de uma agenda, a grade (adicionar, alterar ou remover período) ou os períodos de um dia com a página aberta antes de outra mudança, nada é gravado e a página reabre com o estado atual e a mensagem de conflito.

### Integração com a página do paciente

No `ready()`: a aba "Consultas" (`register_patient_section`, ordem 20), a linha do tempo ("Consulta agendada", "Consulta por ordem de chegada" enquanto ela não aconteceu, "Consulta realizada", "Falta", "Consulta cancelada", sem observação), o relatório do titular (data, código e situação de cada consulta legível; na ordem de chegada, o período em vez da hora; nunca a prioridade) e o passo "Agenda médica" da lista de configuração. Cada contribuição só mostra consultas de agendas que o ator lê.

### API REST

Em `/api/v1/o/<org>/apps/med_scheduling/`:

| Método e caminho | O que faz | Token |
|---|---|---|
| `GET schedules/` | Agendas legíveis (`ScheduleInfo`) | `scheduling:read` |
| `GET schedules/<id>/slots/?start=&end=&type=` | Horários livres (`Slot`, com `appointment_type_ids`: os tipos do período; vazio vale todos os da agenda), datas `AAAA-MM-DD`, até 62 dias | `scheduling:read` |
| `GET appointments/?schedule=&patient=&start=&end=&status=&cursor=&page_size=` | Consultas (`AppointmentInfo`, sem observação) | `scheduling:read` |
| `POST appointments/` | Marca; exige `Idempotency-Key`; campos `schedule`, `patient`, `appointment_type`, `starts_at` (ISO 8601 com fuso) e opcionais `duration_minutes`, `fit_in`, `notes`, `payment_kind` (sem ele, a forma de pagamento do tipo), `room`; devolve 201 com `ETag` | `scheduling:write` |
| `GET appointments/<id>/` | Detalhe (`AppointmentDetail`, com a observação), com `ETag` | `scheduling:read` |
| `POST appointments/<id>/<mudança>/` | `confirm`, `check-in`, `start`, `complete`, `no-show`, `cancel` (`reason`, `note`) e `reschedule` (`starts_at`, `schedule`); exigem `If-Match` com a revisão | `scheduling:write` |

Toda rota aceita a sessão do navegador e o token de um cliente fora dele (o access token OIDC de um cliente nativo, como o Medvita Desktop, ou um token `skt_`) nos métodos da coluna "Token", com as mesmas respostas, filtros, `ETag`, `If-Match` e `Idempotency-Key` da sessão. O escopo só restringe: o serviço autoriza o papel da pessoa como para a sessão, e um token com o escopo continua sem ver o que o papel não alcança. O token amplo (`openid profile email`) leva todos os escopos; um cliente que o operador limitou (`native_client register --scope`) precisa do escopo da coluna e do escopo de tabela do contêiner que o serviço autoriza (`med_scheduling.practice:read` e `med_scheduling.schedule:read`, e as ações de escrita da agenda para marcar). Sem o escopo, a resposta é 403 `permission_denied` ("O token não tem o escopo exigido."); método fora da coluna é 403 `token_not_allowed`. Cada operação aparece no `/api/v1/openapi.json` só para quem pode chamá-la.

Campo fora da lista é 400; sem revisão é 400; revisão vencida é 409; agenda sem acesso ou de outra organização é 404. Sem exclusão pela API.

## Acceptance

- Só o administrador configura o consultório; a configuração é idempotente pela chave e única por organização.
- A recepção lê profissionais, salas e tipos e não os altera; a organização B não vê nada da A.
- O tipo tem forma de pagamento; a consulta marcada sem dizê-la herda a do tipo, e um valor explícito vence.
- Uma agenda sem tipos escolhidos atende todos os tipos ativos; com tipos escolhidos, marcar outro tipo responde `type_not_allowed` e ele não tem horário livre.
- A duração da marcação é a informada, depois a da agenda para o tipo, depois a do tipo; fora de 5 a 480 minutos é recusada.
- Quem altera a agenda (inclusive o profissional dono) escolhe os tipos dela; quem só lê não; revisão vencida não grava e mostra o conflito.
- A página de marcar lista só os tipos da agenda, traz a duração sugerida e recalcula os horários com a duração digitada, sem script.
- Um período da grade atende os tipos que lista, ou todos os da agenda quando não lista nenhum; horários livres e marcação seguem a lista, e o encaixe dispensa a lista do período, nunca a da agenda.
- Gravar a mesma grade não cria nem exclui linha; mudar os tipos de um período mantém o período; a faixa antiga com um tipo só continua valendo.
- São recusados: mais de 100 períodos, períodos sobrepostos, e tipo novo num período que seja de outra organização, inativo ou não atendido pela agenda.
- Pela página da agenda se adiciona um período em vários dias de uma vez, três ou mais períodos no mesmo dia, e se altera e remove um período; a sobreposição aparece no campo; quem só lê a agenda vê a semana e não a altera.
- A agenda do dia faz o mesmo número de consultas ao banco com 1 ou 8 períodos com tipos.
- A grade aceita modo e vagas por período; vagas num período de hora marcada, modo desconhecido e tipo sem o modo do período são recusados.
- Marcar por ordem de chegada grava os limites do período e a duração planejada; `mode_mismatch` nos dois sentidos, e o encaixe com hora dentro de um período de ordem de chegada é aceito.
- Além das vagas, ou do tempo aberto do período quando não há vagas, a marcação responde `session_full`; cancelar libera a vaga, o encaixe passa, e o período todo bloqueado não aceita nem encaixe.
- Duas consultas da mesma sessão numa agenda com sala não respondem `room_unavailable`; a de outra agenda na mesma sala responde.
- A chegada numera 1, 2, 3 na sessão; o número de uma cancelada não é reaproveitado; o prioritário passa à frente; `set_priority` corrige com CAS; revisão vencida na chegada não numera.
- Falta na ordem de chegada só depois do fim do período; quem já chegou não é remarcado.
- O calendário tem um evento por sessão, com a contagem certa depois de marcar e de cancelar e removido com a última cancelada, sem nome nem código; nenhuma consulta de ordem de chegada tem evento próprio.
- A prioridade não aparece em `AppointmentInfo`, em evento nem na notificação da chegada, e sai `[REDACTED]` na auditoria.
- Recepção e médico leem a fila; quem não lê a agenda e a organização B recebem `NotFound`.
- O dia alterado segue os períodos dele e não a grade; a exceção é criada, trocada e limpa com CAS; zero períodos, sobreposição e data passada são recusados; salvar a grade semanal não apaga dia alterado.
- Sem confirmação, o dia que levaria consultas para a ordem de chegada responde `plan_conflicts` e nada muda; confirmado com a lista vista, as consultas mantêm o código, vão para a sessão, voltam a "agendada", trocam o evento do calendário pelo da sessão e publicam `appointment_rescheduled`.
- A marcação feita entre a conferência e a confirmação responde `plan_changed`, e a página mostra a lista de novo.
- Nenhuma confirmação vence: consulta fora dos períodos novos, sessão de ordem de chegada virando hora marcada e sessão com chegada registrada mudando de limites; a consulta em atendimento não é tocada.
- A grade semanal que troca o modo de um período sob consultas marcadas é recusada e passa valendo depois da última; a página do período oferece essa data.
- A conferência lista código e horário, e o nome só para quem lê o paciente; quem só lê a agenda vê os dias alterados e não os altera.
- Nome, número do conselho e CPF do profissional saem `[REDACTED]` na auditoria.
- Um grupo removido por `set_schedule_access` perde o acesso à agenda e ao calendário dela.
- Com o `skeleton_calendar` desativado, a agenda médica fica indisponível.
- Pelas páginas, a recepção marca, registra a chegada, remarca e cancela; revisão vencida mostra a mensagem de conflito.
- O título do evento no calendário nunca leva o nome do paciente; quem lê a agenda e não o paciente vê só o código.
- A agenda do dia faz o mesmo número de consultas ao banco com 1 ou 7 consultas.
- A API nunca devolve a observação numa lista e recusa campos de sistema.
