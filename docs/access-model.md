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

A agenda anda com uma tabela de outra app e o acesso das duas tem de coincidir:

| Contêiner | Espelho | Quem iguala |
|---|---|---|
| `Schedule` | o calendário dele no `skeleton_calendar` | `SchedulingService.set_schedule_access` |

Mudar o acesso de um lado só, pela tela genérica de acesso do núcleo, quebra a projeção (consultas que não aparecem no calendário). Use sempre o método da app.

O caixa (`CashDesk`) **não** tem espelho: o livro contábil autoriza títulos, baixas e lançamentos de regra pelo registro de origem do financeiro (a conta, o pagamento, o movimento), e o caixa guarda as contas do livro de cada forma de pagamento, resolvidas no `setup` (ADR-002 do financeiro).

A matriz "quem lê o quê" do exemplo abaixo é conferida por `tests/test_isolation_matrix.py`: recepção lê paciente, consulta e conta; profissional lê paciente, consulta, prontuário e atendimento; financeiro lê paciente e conta; administrador lê tudo; ninguém da organização B lê nada da A.

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

## Clientes fora do navegador

As APIs REST das quatro apps aceitam, além da sessão, o access token OIDC de um cliente nativo (o Medvita Desktop) e os tokens `skt_` do núcleo, nos métodos que cada view declara em `token_methods` (#61). Nada muda nas regras acima: o token age como a pessoa, o serviço autoriza o papel dela pelo contêiner, a MFA de administrador e a separação entre organizações são as da sessão, e um token nunca administra.

| App | Escopo de leitura | Escopo de escrita |
|---|---|---|
| `med_patients` | `patients:read` | `patients:write` |
| `med_scheduling` | `scheduling:read` | `scheduling:write` |
| `med_records` | `records:read` | nenhum: a escrita clínica é só pelas páginas, e a API do prontuário só aceita `GET` com token |
| `med_finance` | `finance:read` | `finance:write` |

O escopo só restringe. Um token sem o escopo da app recebe 403 antes da view; com ele, o serviço ainda exige o papel e o escopo de tabela do contêiner, que o núcleo aplica num ponto só. O token amplo (`openid profile email`) leva todos; um cliente que o operador limitou precisa dos dois, como `records:read` e `med_records.archive:read`. As tabelas e os métodos de cada app estão na seção "API REST" do `docs/spec.md` dela.

Cada leitura de conteúdo clínico grava na trilha do prontuário (`AccessLog`) a origem da requisição: sessão web, cliente nativo com o `client_id` (o identificador do aplicativo registrado pelo operador, nunca uma pessoa ou um segredo), token de API ou outra. As leituras anteriores a esta mudança ficam como sessão web, a única credencial que as apps aceitavam.
