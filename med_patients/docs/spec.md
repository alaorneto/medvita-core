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

## Acceptance

- Com organizações A e B, ninguém de A obtém paciente de B, nem por UUID conhecido.
- Sem concessão no cadastro, o paciente é invisível; leitura no cadastro lê e não altera; alteração no cadastro altera.
- Com o cadastro excluído, os pacientes somem; sem a permissão de tabela do cadastro, são recusados até ao dono.
- O `setup` é idempotente pela chave, só existe um cadastro padrão por organização e só o administrador o faz.
