# Pacientes

O paciente é um registro da organização, nunca um usuário. Esta app guarda identificação, contatos, responsáveis, convênios e consentimentos, e oferece os pontos de extensão da página do paciente às outras apps. Ela não guarda dado clínico nem financeiro.

## Contract

### Ativação

`med_patients` é instalada globalmente e ativada por organização; instalar o código não concede permissões. A app nasce indisponível e desativada: a plataforma concede a disponibilidade e cada organização ativa a app.

### Tema da instância

Por ser a app que toda instalação da suíte tem, `med_patients` carrega o tema Medvita da instância em `themes/medvita/` (`runtime.instance_themes`, `id` `io.medvita.patients.theme.medvita`). É dado estático validado pelo núcleo, sem código da app: aparece em `/platform/appearance/` como tema da app, o administrador da plataforma o ativa, e a desinstalação da app o tira do catálogo. `tests/test_theme.py` roda `assert_app_themes_valid` e confere que o CSS não fixa token de marca, para a cor de uma clínica continuar vencendo. O `README.md` do diretório diz a origem de cada arquivo.

### Acesso

O único contêiner é o `PatientRegistry` (o cadastro de pacientes da clínica, `SecuredRecord` exposto). Toda outra tabela é derivada dele (`TableSpec.access_parent`): ler um paciente exige `read` no cadastro, criar, alterar, excluir ou restaurar exige `update` nele. Operações de privacidade exigem `manage_access` no cadastro. O modelo completo está em `docs/access-model.md` da raiz do repositório.

O `setup` (só com a capacidade `access.manage`) cria o cadastro padrão, privado e do administrador, dá ao papel `member` leitura e alteração da tabela do cadastro e concede o cadastro aos grupos: escrita (leitura e alteração) e leitura. Pelo gateway genérico do núcleo o cadastro só é renomeado: ele nasce pelo `setup` e não é excluído por lá.

### Modelo de dados

"P" marca os campos em `personal_fields`: legíveis por quem lê o cadastro e `[REDACTED]` na auditoria. Nenhum campo desta app é `sensitive_fields`: não há dado de saúde aqui.

**`PatientRegistry`** (contêiner)

| Campo | Regra |
|---|---|
| `name` | obrigatório, até 120; único por organização entre os vivos |
| `is_default` | no máximo um cadastro padrão vivo por organização |

**`Patient`** (derivada do cadastro)

| Campo | P | Regra |
|---|---|---|
| `registry` | | imutável |
| `code` | | `P` + 6 dígitos da sequência `med_patients.patient`; único na organização; imutável |
| `full_name` | P | obrigatório, até 200 |
| `social_name` | P | quando preenchido, é o nome exibido (`display_name`) |
| `search_name` | P | nome e nome social em minúsculas e sem acento, calculado pelo serviço; fora de `read_fields` |
| `birth_date` | P | não pode ser futura |
| `sex` | P | `female`, `male`, `intersex`, `unknown` |
| `cpf` | P | 11 dígitos com dígitos verificadores válidos; único na organização entre os vivos, quando preenchido |
| `national_health_card` | P | CNS de 15 dígitos, conferido pelo algoritmo oficial |
| `identity_document`, `mother_name` | P | texto livre |
| `phone`, `phone_secondary` | P | dígitos com DDI opcional (`+55...`), de 10 a 13 dígitos |
| `email` | P | email válido |
| `contact_preference` | | `phone`, `whatsapp`, `email`, `none` |
| `postal_code`, `street`, `number`, `complement`, `district`, `city`, `state` | P | CEP de 8 dígitos; UF válida |
| `status` | | `active`, `inactive`, `deceased`; `deceased_on` obrigatório quando `deceased` |
| `notes` | P | observação administrativa, nunca clínica |
| `processing_restricted` | | restrição de tratamento (LGPD) |
| `anonymized_at` | | preenchido só pela anonimização |

**`PatientGuardian`** (derivada do paciente, dois saltos até o cadastro)

| Campo | P | Regra |
|---|---|---|
| `patient` | | imutável |
| `name` | P | obrigatório, até 200 |
| `relationship` | | `mother`, `father`, `legal_guardian`, `spouse`, `child`, `caregiver`, `other` |
| `cpf`, `phone`, `email`, `notes` | P | validados como os do paciente |
| `is_legal_representative`, `is_financial_responsible` | | marcações livres |

Paciente menor de 18 anos (pela data de nascimento) sem responsável vivo marcado como representante legal aparece com `needs_guardian`: é um aviso, não bloqueia o cadastro.

**`PatientCoverage`** (derivada do paciente)

| Campo | P | Regra |
|---|---|---|
| `patient` | | imutável |
| `insurer_name` | | obrigatório, até 120 |
| `insurer_code` | | registro ANS, 6 dígitos |
| `plan_name` | | até 120 |
| `card_number` | P | obrigatório, até 40 |
| `holder_name` | P | titular, até 200 |
| `valid_until` | | validade |
| `is_primary` | | no máximo um principal vivo por paciente; marcar outro desmarca o anterior na mesma transação |

**`Consent`** (derivada do paciente; aceita anexo: o termo digitalizado, em PDF, JPEG ou PNG, até 10 MB)

| Campo | P | Regra |
|---|---|---|
| `patient`, `purpose`, `granted_at` | | imutáveis; a finalidade é um código registrado por uma app ativa |
| `status` | | `granted` ou `revoked`; no máximo um `granted` vivo por paciente e finalidade |
| `revoked_at` | | preenchido na revogação |
| `collected_via` | | `in_person`, `paper`, `digital`, `verbal` |
| `term_version` | | versão do termo apresentado |
| `evidence_note` | P | observação sobre a coleta |

Revogar não apaga: a linha fica com a hora da revogação, e conceder de novo cria outra linha (o histórico é completo). A própria app registra a finalidade `med_patients.contact` ("Contato por telefone, mensagem e email para assuntos do atendimento"); outras apps registram as delas com `register_consent_purpose`. O tratamento para a assistência à saúde em si não depende de consentimento (tem base legal própria): consentimento aqui é para finalidades adicionais.

As linhas que pertencem a um paciente (responsáveis, convênios, consentimentos) não impedem a exclusão lógica dele: a autorização derivada as esconde junto e a restauração do paciente as traz de volta. Registros de outras apps que apontam para o paciente (consultas, prontuários, contas) continuam impedindo a exclusão.

### Importação por CSV

O cadastro aceita uma lista de pacientes em CSV (exemplo com dados fictícios em `docs/examples/patients.csv`):

| Regra | Comportamento |
|---|---|
| Arquivo | UTF-8 (com ou sem BOM) ou Windows-1252; separador `,` ou `;`, decidido pela primeira linha; até 10 MB e 20.000 linhas de dados; a primeira linha tem os nomes das colunas, sem repetição |
| Mapeamento | Na tela, cada coluna vai para um campo de `PatientInput` (ou não é importada); `full_name` é obrigatório e cada campo recebe uma coluna só |
| Conferência | Um job valida cada linha com as regras do cadastro e mostra o relatório: linha inválida (`invalid_<campo>`) ou CPF já cadastrado ou repetido no arquivo (`duplicate_cpf`) |
| Aplicação | Jobs de 200 linhas, cada um na própria transação, como quem enviou o arquivo; CPF já cadastrado é pulado, nunca sobrescrito; cada paciente nasce pelo mesmo caminho do cadastro manual (mesma sequência, mesmos eventos) com uma chave derivada do lote e da linha, então repetir um lote não duplica |
| Permissão | Se quem enviou perdeu a escrita no cadastro, o lote termina em `failed` com o código `forbidden` |
| Dados | O relatório guarda só o número da linha e o código, nunca o valor de uma célula; célula é sempre texto (o relatório baixado neutraliza fórmula com `'`); o texto do arquivo fica no lote só até ele terminar; o arquivo original fica anexo ao lote, com nome fixo, e segue a retenção de anexos do núcleo |

### Direitos do titular

Só quem tem `manage_access` no cadastro (permissão de tabela mais dono ou administrador) vê a aba Privacidade e usa estas operações:

| Operação | Comportamento |
|---|---|
| Relatório do titular (`data_report`) | Cadastro, responsáveis, convênios, consentimentos e as seções das apps ativas (`register_patient_data_provider`); página imprimível. Gerar não altera dado: fica registrado só no log estruturado, com o `sysid` do paciente e do ator |
| Restrição de tratamento (`restrict_processing`) | O cadastro continua legível e encontrável, mas nada sobre o paciente muda até a restrição sair |
| Anonimização (`anonymize`) | Só quando nenhuma guarda de retenção veta. O nome vira "Paciente anonimizado <código>", todo campo pessoal é limpo, responsáveis e convênios recebem tombstone, consentimentos perdem a observação, o paciente fica inativo e somente leitura. A auditoria anterior já está redigida. Irreversível: a tela pede o código do paciente |

Com o prontuário dentro do prazo de guarda, a guarda do `med_records` veta a anonimização; a tela explica e oferece só a restrição de tratamento. O aviso vem antes da tentativa (#134): a aba Privacidade pergunta às mesmas guardas por `anonymization_vetoes` e, com um veto (ou uma guarda que falha), mostra o motivo no lugar do formulário de anonimização; `anonymize` pergunta de novo ao gravar, então um envio forjado continua recusado.

### Telas

Revogar um consentimento, remover um responsável ou um convênio e registrar o óbito passam por uma página de confirmação com o alvo e a consequência (#119): os botões da tela são links para a confirmação; a do óbito exige a data antes. Os campos de dado pessoal e a busca não entram no histórico de formulário do navegador (#120).

Todas em `/o/<org>/apps/med_patients/`, pelo `PatientService`; paciente inexistente, de outra organização ou ilegível responde 404.

| Rota | Tela |
|---|---|
| `med_patients:list` | Busca por nome, CPF, código ou final do telefone, filtro de situação e paginação por cursor (sem contagem: a página do serviço não a traz); para quem tem `access.manage`, o atalho "Configuração da clínica" e, sem cadastro, o caminho para configurá-lo |
| `med_patients:create` | Cadastro novo; antes de gravar mostra possíveis duplicatas (mesmo CPF, ou mesmo nome e nascimento) e pede confirmação. Aceita `next` da marcação (abaixo) |
| `med_patients:detail` | Onde o paciente abre: a aba Resumo (#136), com o cabeçalho, as abas e os painéis que as apps ativas registram (`register_summary_panel`) e que o ator vê: próxima e última consulta com "Marcar consulta", alergias e medicamentos em uso (só para quem lê um arquivo clínico), saldo em aberto com "Nova conta" e o convênio principal com a validade ("Vencido" ou "Vence em N dias"). Um painel que falha some sozinho; sem painel, a página diz "Nada a resumir para você." |
| `med_patients:registration` | Aba Cadastro: os dados do cadastro e, sob "Alterar situação" (`<details>`, fechado), a troca da situação; o óbito continua pedindo a data e a confirmação. Alterar o cadastro ou a situação volta para cá |
| `med_patients:edit` | Alteração, com a revisão em campo oculto; conflito mostra a mensagem de CAS |
| `med_patients:guardians`, `:coverages`, `:consents` | Subabas de Cadastro (#149), com lista e formulário de inclusão; consentimento aceita o termo digitalizado; convênio com validade passada leva a marca "Vencido", e com validade nos próximos 30 dias, "Vence em N dias" |
| `med_patients:timeline` | Linha do tempo das apps ativas |
| `med_patients:imports`, `:import` | Envio, mapeamento das colunas, conferência, aplicação e relatório da importação. Conferindo ou importando, a página mostra o andamento (linhas processadas de N, numa barra `<progress>`) e o link "Atualizar"; o JS opcional atualiza a região de andamento sozinho e recarrega a página quando o lote sai dessas etapas (sem `meta refresh`). O botão diz "Importar N pacientes" com as linhas válidas da conferência; o relatório mostra até 200 linhas e diz "Mostrando 200 de N" |
| `med_patients:privacy` | Relatório do titular, restrição de tratamento e anonimização (quem gere o acesso do cadastro) |
| `med_patients:setup` | Configuração inicial (administradores) |
| `med_patients:clinic_setup` | "Configuração da clínica": os passos numerados das apps ativas, cada um com feito ou pendente (só quem tem `access.manage`; os outros recebem 404) |

O formulário do paciente vem em quatro grupos (`fieldset` com `legend`): Identificação, Contato, Endereço e Observações; os nomes dos campos não mudam. CPF, telefones e CEP levam `data-mask`, que o `static/med_patients/med_patients.js` opcional usa só para formatar enquanto se digita; sem JS o formulário funciona igual e o servidor normaliza e valida (o erro cita o campo, nunca o valor).

**Volta à marcação (#130).** A marcação liga para `med_patients:create?next=<caminho da marcação>`. A página só aceita `next` que seja caminho local deste host (`url_has_allowed_host_and_scheme`) começando por `/o/<org>/apps/med_scheduling/book/` da organização corrente, sem `..` (nem codificado), barra invertida ou caractere de controle; qualquer outro valor é ignorado. O `next` aceito vai num campo oculto (também no passo das duplicatas) e, depois de criar, a página redireciona para ele com `patient=<sysid>` acrescentado, preservando os demais parâmetros. Sem `next`, abre o paciente criado, como antes. A URL de volta leva só o `sysid`.

**Cabeçalho do paciente (#136).** Um só nas quatro apps: `PatientService().header(...)` (nome, código, idade, sexo, situação, os avisos de menor sem responsável legal, tratamento restrito e anonimizado, e se o ator altera o cadastro) e o template `med_patients/templates/med_patients/_patient_header.html`, que as abas das outras apps incluem no lugar de montar o próprio; cada aba passa a sua ação principal ("Marcar consulta", "Nova conta"). `med_patients/templates/med_patients/_patient_identity.html` é a mesma pessoa numa linha (nome, idade, sexo), para a faixa clínica do prontuário.

As abas vão por uso (`page_tabs`): Resumo, as abas das outras apps (`register_patient_section`, por `order`: Consultas, Prontuário, Financeiro), Cadastro, Linha do tempo e Privacidade. Responsáveis, Convênios e Consentimentos são subabas de Cadastro (#149): a página de cada uma marca a aba Cadastro e mostra a segunda faixa (Dados do paciente, Responsáveis, Convênios, Consentimentos), para que a faixa principal caiba inteira e Privacidade esteja sempre à vista; uma aba de outra app com `order` acima de 55 vem depois delas, e todas somem com a app desativada. O título da aba do navegador leva o código do paciente, nunca o nome. O termo anexado recebe um nome fixo, porque o nome do arquivo enviado pode trazer o nome da pessoa.

### API REST

Em `/api/v1/o/<org>/apps/med_patients/`:

| Método e caminho | O que faz | Token |
|---|---|---|
| `GET patients/?q=&status=&cursor=&page_size=` | Busca (`PatientSummary`) | `patients:read` |
| `POST patients/` | Cadastra; `Idempotency-Key` opcional; devolve 201 com `ETag` | `patients:write` |
| `GET patients/<id>/` | Lê (`PatientInfo`), com `ETag` | `patients:read` |
| `PATCH patients/<id>/` | Altera campos de `PatientInput`; exige `If-Match` com a revisão; campo fora da lista é 400 | `patients:write` |
| `GET patients/<id>/guardians/`, `GET patients/<id>/coverages/` | Responsáveis e convênios | `patients:read` |

Toda rota aceita a sessão do navegador e o token de um cliente fora dele (o access token OIDC de um cliente nativo, como o Medvita Desktop, ou um token `skt_`) nos métodos da coluna "Token", com as mesmas respostas, filtros, `ETag`, `If-Match` e `Idempotency-Key` da sessão. O escopo só restringe: o serviço autoriza o papel da pessoa como para a sessão, e um token com o escopo continua sem ver o que o papel não alcança. O token amplo (`openid profile email`) leva todos os escopos; um cliente que o operador limitou (`native_client register --scope`) precisa do escopo da coluna e do escopo de tabela do contêiner que o serviço autoriza (`med_patients.patientregistry:read`, e `:update` para alterar). Sem o escopo, a resposta é 403 `permission_denied` ("O token não tem o escopo exigido."); método fora da coluna é 403 `token_not_allowed`. Cada operação aparece no `/api/v1/openapi.json` só para quem pode chamá-la.

Sem exclusão nem anonimização pela API.

## Acceptance

- Com organizações A e B, ninguém de A obtém paciente de B, nem por UUID conhecido.
- Sem concessão no cadastro, o paciente é invisível; leitura no cadastro lê e não altera; alteração no cadastro altera.
- Com o cadastro excluído, os pacientes somem; sem a permissão de tabela do cadastro, são recusados até ao dono.
- O `setup` é idempotente pela chave, só existe um cadastro padrão por organização e só o administrador o faz.
- Nenhum evento, log ou mensagem de erro leva nome, documento, contato ou endereço; a auditoria mostra esses campos `[REDACTED]`.
- Duas alterações com a mesma revisão: uma vence, a outra recebe `Conflict("stale_revision")`.
- Um CSV de 500 linhas com 10 inválidas e 5 CPFs repetidos cria 485 pacientes; repetir um lote não duplica.
- Anonimizar com uma guarda que veta é recusado; sem guarda, nenhuma busca pelos dados antigos acha o paciente.
