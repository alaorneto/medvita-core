# Agenda médica: decisões

## Context

A recepção marca consultas na agenda de vários profissionais, e cada profissional manda na própria agenda; a configuração do consultório (profissionais, salas, tipos) é de quem administra. Uma concessão do núcleo vale num registro e só o administrador concede.

## Decision

- **ADR-001, dois contêineres.** `Practice` guarda a configuração e `Schedule` as consultas. A recepção recebe leitura do consultório e escrita nas agendas em que marca; o profissional é dono da própria agenda. Tudo o mais é tabela derivada de um dos dois.
- O profissional aponta para a pessoa (`sk_accounts.User`), não para o vínculo: o vínculo ativo é conferido pelo `OrganizationService` do núcleo, sem tocar em modelos internos.

- **ADR-002, sobreposição resolvida por trava na agenda.** A marcação trava a linha da agenda e confere o intervalo, em vez de uma restrição de exclusão no banco: o encaixe precisa sobrepor, e a regra de sala cruza agendas. A conferência de sobreposição olha todas as consultas vivas da agenda (e da sala), mesmo as que o ator não poderia listar, porque só responde se o horário está livre.
- **ADR-003, projeção no calendário sem dado do paciente.** O evento gerenciado leva o tipo e o código da consulta; o detalhe fica na app, alcançado pelo caminho do evento.

## Consequences

- Mudar quem administra a configuração é conceder `update` no consultório; mudar quem marca numa agenda é conceder `update` na agenda.
- Toda coluna nova revisa `read_fields`, `personal_fields`, `sensitive_fields` e a migration de infraestrutura.
