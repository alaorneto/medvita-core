# Agenda médica: decisões

## Context

A recepção marca consultas na agenda de vários profissionais, e cada profissional manda na própria agenda; a configuração do consultório (profissionais, salas, tipos) é de quem administra. Uma concessão do núcleo vale num registro e só o administrador concede.

## Decision

- **ADR-001, dois contêineres.** `Practice` guarda a configuração e `Schedule` as consultas. A recepção recebe leitura do consultório e escrita nas agendas em que marca; o profissional é dono da própria agenda. Tudo o mais é tabela derivada de um dos dois.
- O profissional aponta para a pessoa (`sk_accounts.User`), não para o vínculo: o vínculo ativo é conferido pelo `OrganizationService` do núcleo, sem tocar em modelos internos.

- **ADR-002, sobreposição resolvida por trava na agenda.** A marcação trava a linha da agenda e confere o intervalo, em vez de uma restrição de exclusão no banco: o encaixe precisa sobrepor, e a regra de sala cruza agendas. A conferência de sobreposição olha todas as consultas vivas da agenda (e da sala), mesmo as que o ator não poderia listar, porque só responde se o horário está livre.
- **ADR-003, projeção no calendário sem dado do paciente.** O evento gerenciado leva o tipo e o código da consulta; o detalhe fica na app, alcançado pelo caminho do evento.
- **ADR-004, o tipo de atendimento carrega a forma de pagamento.** "Particular", "Unimed" e "Retorno Unimed" são tipos de atendimento, cada um com forma de pagamento e duração padrão; não há cadastro de convênios. A recepção escolhe uma coisa só ao marcar, e a consulta guarda a cópia da forma de pagamento (um valor explícito na marcação vence). Um cadastro de convênios com carteirinha e TISS fica para quando houver faturamento de convênio.
- **ADR-005, os tipos de uma agenda em tabela própria, com "nenhuma linha" valendo "todos".** `ScheduleAppointmentType` é derivada da agenda e guarda, por tipo, a duração naquela agenda e os modos permitidos. A agenda que ninguém configurou atende todos os tipos ativos: a instalação existente não muda de comportamento e não precisa de migration de dados. A troca usa a revisão da agenda como CAS, a mesma da grade, e compara em vez de recriar: nada é apagado fisicamente e a linha que continua mantém a identidade na auditoria.
- **ADR-006, os tipos de um período em tabela de ligação, e a grade gravada por comparação.** `AvailabilityRuleType` liga o período aos tipos que ele atende, com integridade referencial e uma linha auditável por tipo; a lista vazia vale "todos os da agenda", como em ADR-005. Descartados: a lista de tipos em JSON na faixa (sem integridade referencial, e o núcleo pede a ligação explícita) e várias faixas iguais, uma por tipo (a regra de não sobrepor períodos deixaria de valer). A tabela é derivada do período, a dois saltos da agenda: como a rota de acesso exige o período vivo, `set_availability` exclui os tipos antes do período. A coluna `appointment_type` da faixa, de um tipo só, continua lida e deixa de ser escrita; ela é limpa quando os tipos do período mudam, sem migration de dados. `set_availability` compara a grade pedida com a existente em vez de excluir e recriar tudo: salvar a página não troca a identidade dos períodos nem enche a auditoria de linhas iguais. O tipo é conferido só quando entra num período, para que tirar um tipo da agenda não impeça de salvar a grade que ainda o lista.
- **ADR-007, o editor da grade acrescenta, altera e remove um período de cada vez.** A página manda ao serviço a grade inteira (os períodos atuais mais a mudança), com a revisão da agenda como CAS, em vez de um formulário com a semana toda: o formulário único limitava o número de períodos por dia e fazia de cada gravação uma troca completa. A sobreposição é conferida no formulário, com a mesma função pura do serviço (`slots.collide`), para apontar o campo; o serviço confere de novo. O JavaScript da app é um arquivo estático opcional: as páginas trazem todos os campos e o script só recolhe os vazios e adianta a sugestão de duração.

## Consequences

- Mudar quem administra a configuração é conceder `update` no consultório; mudar quem marca numa agenda é conceder `update` na agenda.
- Toda coluna nova revisa `read_fields`, `personal_fields`, `sensitive_fields` e a migration de infraestrutura.
- Quem decide os tipos que um médico atende é quem altera a agenda dele (o próprio médico ou a recepção), não quem administra o consultório; os tipos em si continuam sendo configuração do consultório.
- Tabela derivada de nome longo ganha `db_table` curto: os identificadores de infraestrutura do núcleo derivam do nome da tabela e têm de caber em 63 bytes (`skeleton.E033`).
- Quem lê os períodos de várias agendas lê os tipos deles em lote (`_rule_kinds`), nunca período a período: a política de dois saltos custa mais por consulta.
- Um período pode listar um tipo que a agenda deixou de atender. Ele não dá horário a esse tipo (a agenda recusa antes) e a página mostra o tipo marcado até alguém alterar o período.
