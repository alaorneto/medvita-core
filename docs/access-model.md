# Modelo de acesso

**Regra única:** cada app tem um ou dois contêineres (`SecuredRecord` com `expose_api=True`), e toda outra tabela é **derivada** de um contêiner (`OrganizationRecord`, `expose_api=False`, `TableSpec(access_parent="<fk>")`). Ler um filho exige `read` no contêiner; criar, alterar, excluir ou restaurar um filho exige `update` no contêiner. O acesso ao contêiner é o de qualquer `SecuredRecord`: dono, administrador da organização ou concessão por registro a grupo, papel ou pessoa. A permissão de tabela que vale para um filho é a da tabela do contêiner.

| App | Contêiner | O que representa | Quem costuma receber `read` | Quem costuma receber `update` |
|---|---|---|---|---|
| `med_patients` | `PatientRegistry` | O cadastro de pacientes da clínica | todos os grupos | Recepção, Profissionais |
| `med_scheduling` | `Practice` | O consultório: estabelecimento, profissionais, salas, tipos de atendimento, lista de espera | todos os grupos | administrador e o grupo de gestão (em geral a Recepção, que cuida da lista de espera) |
| `med_scheduling` | `Schedule` | A agenda de um profissional, sala ou equipamento: grade (com os tipos de cada período), bloqueios, tipos atendidos e consultas | Recepção, Profissionais | Recepção, o próprio profissional (dono) |
| `med_records` | `Archive` | Um arquivo clínico: da clínica inteira ou de um profissional | Profissionais do arquivo | Profissionais do arquivo |
| `med_finance` | `CashDesk` | Um caixa (ponto de recebimento) | Recepção, Financeiro | Recepção, Financeiro |
| `med_finance` | `PriceList` | Uma tabela de preços | Recepção, Financeiro, Profissionais | Financeiro |

## Consequências

- "A recepção agenda, mas não lê evolução" sai sozinho: a Recepção não recebe concessão em nenhum `Archive`.
- Um consultório com dois médicos que não compartilham prontuário usa dois `Archive`, cada um com a própria concessão. Uma clínica com prontuário único usa um.
- O cadastro dos tipos de atendimento é do consultório (`Practice`); quais tipos uma agenda atende, e com que duração, é da agenda (`Schedule`): o médico dono escolhe os da própria agenda sem poder mudar o cadastro.
- Uma tabela pode ser derivada de outra derivada, até o limite de saltos do núcleo: os tipos de um período da grade (`AvailabilityRuleType`) chegam à agenda pelo período. O elo do meio precisa estar vivo; por isso quem exclui o período exclui antes os filhos dele, e quem lê os filhos de vários períodos lê em lote.
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

O calendário de uma agenda é **gerenciado** pela agenda médica: o núcleo guarda a app de origem e o caminho da agenda, e as páginas do calendário dele não renomeiam, compartilham nem excluem esse calendário (409), só apontam para a agenda. `create_schedule` cria o calendário já marcado; as agendas criadas antes do marcador são marcadas por `SchedulingService.claim_schedule_calendars`, passo idempotente de quem tem `access.manage`. Os calendários comuns da clínica (os que não são de uma agenda) nascem na página de calendários compartilhados do núcleo, com o acesso decidido lá.

O link de assinatura de um calendário é do núcleo e segue o mesmo acesso: é um por pessoa e calendário, e a autorização é relida a cada pedido. Quem sai da agenda por `set_schedule_access` deixa de receber os eventos pelo link no pedido seguinte, sem revogar nada à mão; se voltar a ler, o link volta a responder.

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

## Pessoas externas (portal)

Nenhuma das quatro apps atende a pessoa externa do portal do núcleo: os métodos de serviço não têm `allow_external`, então no portal todos respondem `Forbidden("external_not_allowed")`, e `authorized_queryset` nega antes de qualquer consulta. O agendamento pelo paciente (alaorneto/medvita-core#99) espera o núcleo deixar uma app numerar, publicar evento e escrever no calendário que ela gerencia dentro do portal (alaorneto/skeleton#741); a decisão e a investigação estão no ADR-017 de `med_scheduling/docs/adr.md`. Quando vier, a regra continua a desta página: nenhuma concessão nova na agenda para a pessoa externa, autorização pela publicação da agenda e pelo vínculo do paciente.
