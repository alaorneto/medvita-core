# Pacientes

O paciente é um registro da organização, nunca um usuário. Esta app guarda identificação, contatos, responsáveis, convênios e consentimentos, e oferece os pontos de extensão da página do paciente às outras apps. Ela não guarda dado clínico nem financeiro.

## Contract

### Ativação

`med_patients` é instalada globalmente e ativada por organização; instalar o código não concede permissões. A app nasce indisponível e desativada: a plataforma concede a disponibilidade e cada organização ativa a app.

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

### Telas

Todas em `/o/<org>/apps/med_patients/`, pelo `PatientService`; paciente inexistente, de outra organização ou ilegível responde 404.

| Rota | Tela |
|---|---|
| `med_patients:list` | Busca por nome, CPF, código ou final do telefone, filtro de situação e paginação por cursor |
| `med_patients:create` | Cadastro novo; antes de gravar mostra possíveis duplicatas (mesmo CPF, ou mesmo nome e nascimento) e pede confirmação |
| `med_patients:detail` | Página do paciente: cabeçalho (nome, idade, código, situação, avisos de responsável e de tratamento restrito), abas e situação do cadastro |
| `med_patients:edit` | Alteração, com a revisão em campo oculto; conflito mostra a mensagem de CAS |
| `med_patients:guardians`, `:coverages`, `:consents` | Abas com lista e formulário de inclusão; consentimento aceita o termo digitalizado |
| `med_patients:timeline` | Linha do tempo das apps ativas |
| `med_patients:imports`, `:import` | Envio, mapeamento das colunas, conferência, aplicação e relatório da importação |
| `med_patients:setup` | Configuração inicial (administradores) |

As abas das outras apps (`register_patient_section`) entram depois das próprias, em ordem, e somem com a app desativada. O título da aba do navegador leva o código do paciente, nunca o nome. O termo anexado recebe um nome fixo, porque o nome do arquivo enviado pode trazer o nome da pessoa.

### API REST

Em `/api/v1/o/<org>/apps/med_patients/`:

| Método e caminho | O que faz |
|---|---|
| `GET patients/?q=&status=&cursor=&page_size=` | Busca (`PatientSummary`) |
| `POST patients/` | Cadastra; `Idempotency-Key` opcional; devolve 201 com `ETag` |
| `GET patients/<id>/` | Lê (`PatientInfo`), com `ETag` |
| `PATCH patients/<id>/` | Altera campos de `PatientInput`; exige `If-Match` com a revisão; campo fora da lista é 400 |
| `GET patients/<id>/guardians/`, `GET patients/<id>/coverages/` | Responsáveis e convênios |

Sem exclusão nem anonimização pela API.

## Acceptance

- Com organizações A e B, ninguém de A obtém paciente de B, nem por UUID conhecido.
- Sem concessão no cadastro, o paciente é invisível; leitura no cadastro lê e não altera; alteração no cadastro altera.
- Com o cadastro excluído, os pacientes somem; sem a permissão de tabela do cadastro, são recusados até ao dono.
- O `setup` é idempotente pela chave, só existe um cadastro padrão por organização e só o administrador o faz.
