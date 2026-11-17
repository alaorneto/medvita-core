# Modelo de acesso

**Regra única:** cada app tem um ou dois contêineres (`SecuredRecord` com `expose_api=True`), e toda outra tabela é **derivada** de um contêiner (`OrganizationRecord`, `expose_api=False`, `TableSpec(access_parent="<fk>")`). Ler um filho exige `read` no contêiner; criar, alterar, excluir ou restaurar um filho exige `update` no contêiner. O acesso ao contêiner é o de qualquer `SecuredRecord`: dono, administrador da organização ou concessão por registro a grupo, papel ou pessoa. A permissão de tabela que vale para um filho é a da tabela do contêiner.

| App | Contêiner | O que representa | Quem costuma receber `read` | Quem costuma receber `update` |
|---|---|---|---|---|
| `med_patients` | `PatientRegistry` | O cadastro de pacientes da clínica | todos os grupos | Recepção, Profissionais |
| `med_scheduling` | `Practice` | O consultório: estabelecimento, profissionais, salas, tipos de atendimento, lista de espera | todos os grupos | administrador e o grupo de gestão (em geral a Recepção, que cuida da lista de espera) |
| `med_scheduling` | `Schedule` | A agenda de um profissional, sala ou equipamento | Recepção, Profissionais | Recepção, o próprio profissional (dono) |
| `med_records` | `Archive` | Um arquivo clínico: da clínica inteira ou de um profissional | Profissionais do arquivo | Profissionais do arquivo |
| `med_finance` | `CashDesk` | Um caixa (ponto de recebimento) | Recepção, Financeiro | Recepção, Financeiro |
| `med_finance` | `PriceList` | Uma tabela de preços | Recepção, Financeiro, Profissionais | Financeiro |

## Consequências

- "A recepção agenda, mas não lê evolução" sai sozinho: a Recepção não recebe concessão em nenhum `Archive`.
- Um consultório com dois médicos que não compartilham prontuário usa dois `Archive`, cada um com a própria concessão. Uma clínica com prontuário único usa um.
- Regras além do contêiner ficam no serviço da app e só restringem: só o autor altera o rascunho de uma evolução; só quem abriu o caixa o fecha (ou o dono do `CashDesk`).
- Todo queryset de serviço começa em `authorized_queryset(Modelo, user=actor, action=...)`.
- Operações de privacidade (relatório do titular, restrição de tratamento, anonimização) exigem `manage_access` no `PatientRegistry`: permissão de tabela mais dono ou administrador.
- Configuração inicial (`setup` de cada app) exige a capacidade `access.manage`, porque cria contêiner e concede acesso a grupos.
- Cada `setup` dá ao papel `member` a permissão de tabela do contêiner (`AccessService.grant_member_table_access`): quem decide o acesso real são as concessões por registro.

## Acesso em espelho

Dois contêineres andam com uma tabela de outra app e o acesso das duas tem de coincidir:

| Contêiner | Espelho | Quem iguala |
|---|---|---|
| `Schedule` | o calendário dele no `skeleton_calendar` | `SchedulingService.set_schedule_access` |
| `CashDesk` | o livro dele no `skeleton_ledger` | `FinanceService.set_desk_access` |

Mudar o acesso de um lado só, pela tela genérica de acesso do núcleo, quebra a projeção (consultas que não aparecem no calendário, recebimentos recusados pelo livro). Use sempre o método da app.

## Grupos sugeridos

O administrador cria os grupos na tela de acesso da organização (`/o/<org>/access/`); o núcleo não tem serviço para criar grupo por app. Sugestão: **Recepção**, **Profissionais de saúde**, **Financeiro**.

## Exemplo: clínica com recepção, dois médicos e financeiro

| Contêiner | Recepção | Dra. Ana | Dr. Bruno | Financeiro |
|---|---|---|---|---|
| Cadastro de pacientes | lê e altera | lê e altera | lê e altera | lê |
| Consultório | lê | lê | lê | lê |
| Agenda da Dra. Ana | lê e altera | dona | lê | — |
| Agenda do Dr. Bruno | lê e altera | lê | dono | — |
| Arquivo clínico da Dra. Ana | — | lê e altera | — | — |
| Arquivo clínico do Dr. Bruno | — | — | lê e altera | — |
| Caixa da recepção | lê e altera | — | — | lê e altera |
| Tabela de preços | lê | lê | lê | lê e altera |

Com um prontuário único, os dois médicos dividem um `Archive` e ganham `update` nele pelo grupo Profissionais de saúde.
