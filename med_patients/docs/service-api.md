# API de serviços: Pacientes

Referência de `PatientService` (`applications.med_patients.service_api`). O contrato geral está na [API de serviços do núcleo](https://github.com/alaorneto/skeleton/blob/v0.3.0/docs/service-api.md).

## Visão geral

`PatientService` dá às outras apps e às superfícies desta app o cadastro de pacientes da organização atual, com a autorização do ator do contexto. Todos os métodos exigem a app ativa (`Unavailable`), contexto de organização aberto pelo chamador e `actor` igual ao ator do contexto (`Forbidden`, código `actor_mismatch`). Comandos rodam num savepoint da transação do chamador: um erro não deixa nada gravado. Paciente inexistente, de outra organização ou ilegível respondem o mesmo `NotFound`.

Para listar pacientes de outra app, use `PatientSummary` (`summary`, `summaries`, `search`): ele não traz contato, documento nem endereço. `PatientInfo` (`get`) é para a tela do cadastro.

## Dependência

`app_id`: `io.katua.sk.med.patients`. Faixa no manifesto do consumidor: a versão corrente da suíte, `>=0.1.0,<0.2.0` na primeira linha. Importe só o módulo `service_api` desta app.

<!-- BEGIN GENERATED: tools/service_reference.py -->

## Serviços

### `PatientService`

#### `add_coverage(*, actor, patient_id, data, idempotency_key=None) -> CoverageInfo`

Add a health plan card to a patient; marking it primary unmarks the previous primary one.

- **Autorização:** alteração no cadastro do paciente.
- **Erros:** NotFound; Forbidden se só lê; InvalidInput com o nome do campo; Conflict("processing_restricted", "anonymized").
- **Efeitos:** grava o convênio (e desmarca o principal anterior) na mesma transação; a mesma chave do mesmo ator devolve o já criado.

#### `add_guardian(*, actor, patient_id, data, idempotency_key=None) -> GuardianInfo`

Add a guardian or contact person to a patient.

- **Autorização:** alteração no cadastro do paciente.
- **Erros:** NotFound; Forbidden se só lê; InvalidInput com o nome do campo; Conflict("processing_restricted", "anonymized").
- **Efeitos:** grava o responsável; a mesma chave do mesmo ator devolve o já criado.

#### `anonymize(*, actor, patient_id, expected_revision) -> PatientInfo`

Erase the identification of a patient for good, when no retention guard vetoes, with CAS.

- **Autorização:** ``manage_access`` no cadastro.
- **Erros:** NotFound; Forbidden; Conflict("stale_revision", "anonymized"); Conflict("retention", motivo) quando uma guarda veta.
- **Efeitos:** grava o cadastro anonimizado e as exclusões lógicas; nenhum evento de domínio.

#### `apply_import(*, actor, batch_id, expected_revision) -> ImportStatus`

Create the patients of a validated batch, by jobs of 200 rows, with CAS.

- **Autorização:** alteração no cadastro do lote (conferida de novo por cada job).
- **Erros:** NotFound; Forbidden; Conflict("stale_revision"); Conflict("import_state") fora de "validado".
- **Efeitos:** muda a situação para "importando" e enfileira o primeiro job.

#### `consent_purposes(*, actor) -> tuple[ConsentPurposeInfo, ...]`

Consent purposes declared by the apps active in the organization.

- **Autorização:** vínculo ativo do ator.
- **Erros:** nenhum além do contrato.
- **Efeitos:** nenhum.

#### `consents(*, actor, patient_id) -> tuple[ConsentInfo, ...]`

Every consent of a patient, granted and revoked, the most recent first.

- **Autorização:** leitura do cadastro do paciente.
- **Erros:** NotFound para paciente inexistente, de outra organização ou ilegível.
- **Efeitos:** nenhum.

#### `coverages(*, actor, patient_id) -> tuple[CoverageInfo, ...]`

Health plan cards of a patient, the primary one first.

- **Autorização:** leitura do cadastro do paciente.
- **Erros:** NotFound para paciente inexistente, de outra organização ou ilegível.
- **Efeitos:** nenhum.

#### `create(*, actor, data, registry_id=None, idempotency_key=None) -> PatientInfo`

Register a patient in a registry (the default one when not given).

- **Autorização:** alteração (``update``) no cadastro.
- **Erros:** NotFound para cadastro inexistente ou ilegível; Forbidden se só lê o cadastro; InvalidInput com o nome do campo inválido (nunca o valor); Conflict("integrity_conflict") para CPF já cadastrado entre os vivos.
- **Efeitos:** valida tudo, depois tira o código da sequência sem lacunas, grava o paciente e publica ``med_patients.patient_created``. A mesma chave do mesmo ator devolve o paciente já criado.

#### `data_report(*, actor, patient_id) -> PatientDataReport`

Everything the suite keeps about a patient, for the data subject (LGPD art. 18).

- **Autorização:** ``manage_access`` no cadastro (permissão de tabela mais dono ou administrador).
- **Erros:** NotFound para paciente ilegível; Forbidden para quem lê sem gerir o acesso.
- **Efeitos:** registra no log estruturado que o relatório foi gerado (sem nome nem dados).

#### `delete(*, actor, patient_id, expected_revision) -> None`

Delete a patient (tombstone), with CAS; guardians, coverages and consents disappear with it.

- **Autorização:** alteração no cadastro do paciente.
- **Erros:** NotFound; Forbidden; Conflict("stale_revision"); Conflict("retention", motivo) quando uma guarda de retenção registrada veta; Conflict("live_references") quando registros de outras apps ainda apontam para o paciente.
- **Efeitos:** exclusão lógica; os dados continuam no banco e voltam com ``restore``.

#### `find_duplicates(*, actor, cpf='', full_name='', birth_date=None) -> tuple[PatientSummary, ...]`

Live patients that look like the same person: same CPF, or same name and birth date.

- **Autorização:** leitura do cadastro de cada paciente.
- **Erros:** nenhum além do contrato.
- **Efeitos:** nenhum.

#### `get(*, actor, patient_id) -> PatientInfo`

Everything the app keeps about one patient.

- **Autorização:** leitura do cadastro do paciente.
- **Erros:** NotFound para paciente inexistente, de outra organização ou ilegível (a mesma resposta).
- **Efeitos:** nenhum.

#### `grant_consent(*, actor, patient_id, purpose, collected_via, term_version='', evidence_note='', idempotency_key) -> ConsentInfo`

Record a granted consent for a purpose; the digitized term goes as an attachment of it.

- **Autorização:** alteração no cadastro do paciente.
- **Erros:** NotFound; Forbidden se só lê; InvalidInput para finalidade não registrada (ou de app desativada) e forma de coleta desconhecida; Conflict("already_granted") com um consentimento vivo para a mesma finalidade; Conflict("processing_restricted", "anonymized").
- **Efeitos:** grava o consentimento e publica ``med_patients.consent_changed``; a mesma chave do mesmo ator devolve o já criado.

#### `guardians(*, actor, patient_id) -> tuple[GuardianInfo, ...]`

Guardians and contact people of a patient, in the order they were added.

- **Autorização:** leitura do cadastro do paciente.
- **Erros:** NotFound para paciente inexistente, de outra organização ou ilegível.
- **Efeitos:** nenhum.

#### `has_consent(*, actor, patient_id, purpose) -> bool`

Whether the patient has a live granted consent for the purpose.

- **Autorização:** leitura do cadastro do paciente.
- **Erros:** NotFound para paciente inexistente, de outra organização ou ilegível.
- **Efeitos:** nenhum.

#### `import_status(*, actor, batch_id) -> ImportStatus`

The state, counts and report of one import.

- **Autorização:** leitura do cadastro do lote.
- **Erros:** NotFound para lote inexistente, de outra organização ou ilegível.
- **Efeitos:** nenhum.

#### `imports(*, actor) -> tuple[ImportStatus, ...]`

The 50 most recent imports the actor reads.

- **Autorização:** leitura do cadastro de cada lote.
- **Erros:** nenhum além do contrato.
- **Efeitos:** nenhum.

#### `map_import(*, actor, batch_id, mapping, expected_revision) -> ImportStatus`

Say which column feeds which patient field, with CAS, and queue the validation of every row.

- **Autorização:** alteração no cadastro do lote.
- **Erros:** NotFound; Forbidden; InvalidInput para coluna inexistente, campo que não é de ``PatientInput``, campo repetido ou ``full_name`` sem coluna; Conflict("stale_revision"); Conflict("import_state") fora de "enviado" ou "validado".
- **Efeitos:** grava o mapeamento e enfileira o job de validação (situação "validando").

#### `page_tabs(*, actor, patient_id) -> tuple[PatientSectionInfo, ...]`

Every tab of the patient page, in order: the app's own, Privacidade for who manages access to the registry, then the sections of active apps. A page of another app renders the same navigation from it (the route of each tab receives ``org`` and ``patient_id``). A section with ``visible`` shows only when it answers ``True`` for the actor and the patient.

- **Autorização:** leitura do cadastro do paciente.
- **Erros:** NotFound para paciente inexistente, de outra organização ou ilegível.
- **Efeitos:** nenhum.

#### `patient_sections(*, actor) -> tuple[PatientSectionInfo, ...]`

Tabs and shortcuts other apps add to the patient page, in order; only active apps.

- **Autorização:** vínculo ativo do ator; cada aba autoriza a própria página.
- **Erros:** nenhum além do contrato.
- **Efeitos:** nenhum.

#### `registries(*, actor) -> tuple[RegistryInfo, ...]`

Patient registries the actor reads, the default one first.

- **Autorização:** TablePermission read em med_patients.patientregistry e leitura de cada cadastro.
- **Erros:** Forbidden sem a permissão de tabela; Unavailable com a app desativada.
- **Efeitos:** nenhum.

#### `remove_coverage(*, actor, coverage_id, expected_revision) -> None`

Remove a health plan card (tombstone), with CAS.

- **Autorização:** alteração no cadastro do paciente.
- **Erros:** NotFound; Forbidden; Conflict("stale_revision", "processing_restricted", "anonymized").
- **Efeitos:** exclusão lógica do convênio.

#### `remove_guardian(*, actor, guardian_id, expected_revision) -> None`

Remove a guardian (tombstone), with CAS.

- **Autorização:** alteração no cadastro do paciente.
- **Erros:** NotFound; Forbidden; Conflict("stale_revision", "processing_restricted", "anonymized").
- **Efeitos:** exclusão lógica do responsável.

#### `restore(*, actor, patient_id, expected_revision) -> PatientInfo`

Bring back a deleted patient with the same identifier, code and data, with CAS.

- **Autorização:** alteração no cadastro do paciente (o cadastro precisa estar vivo).
- **Erros:** NotFound para paciente inexistente, vivo-ilegível ou de outra organização; Conflict("stale_revision"); Conflict("integrity_conflict") quando o CPF já voltou a ser de outro paciente vivo.
- **Efeitos:** desfaz a exclusão lógica; responsáveis, convênios e consentimentos voltam junto.

#### `restrict_processing(*, actor, patient_id, restricted, expected_revision) -> PatientInfo`

Restrict (or lift the restriction on) the processing of a patient's data, with CAS.

- **Autorização:** ``manage_access`` no cadastro.
- **Erros:** NotFound; Forbidden; InvalidInput; Conflict("stale_revision", "anonymized").
- **Efeitos:** grava a marcação (auditada pelo núcleo).

#### `revoke_consent(*, actor, consent_id, expected_revision) -> ConsentInfo`

Revoke a granted consent, with CAS; the row stays, with the revocation time.

- **Autorização:** alteração no cadastro do paciente.
- **Erros:** NotFound; Forbidden; Conflict("stale_revision"); Conflict("already_revoked").
- **Efeitos:** grava a revogação e publica ``med_patients.consent_changed``.

#### `search(*, actor, query='', status=None, cursor=None, page_size=25) -> Page[PatientSummary]`

Patients the actor reads, by name order, filtered by a free-text query and a status.

- **Autorização:** leitura do cadastro de cada paciente.
- **Erros:** InvalidInput para situação desconhecida, cursor ou tamanho de página inválidos; Forbidden sem a permissão de tabela do cadastro.
- **Efeitos:** nenhum.

#### `set_status(*, actor, patient_id, status, expected_revision, deceased_on=None) -> PatientInfo`

Mark a patient active, inactive or deceased (with the date of death), with CAS.

- **Autorização:** alteração no cadastro do paciente.
- **Erros:** NotFound; Forbidden; InvalidInput para situação desconhecida, óbito sem data ou data futura; Conflict("stale_revision", "anonymized").
- **Efeitos:** grava a situação e publica ``med_patients.patient_status_changed``.

#### `setup(*, actor, name, writer_group_ids=(), reader_group_ids=(), idempotency_key) -> RegistryInfo`

Create the organization's default patient registry and share it with groups.

- **Autorização:** a capacidade ``access.manage`` (administrador da organização) e ``create`` em med_patients.patientregistry.
- **Erros:** Forbidden sem a capacidade ou a permissão de tabela; InvalidInput para nome vazio, chave inválida, mais de 20 grupos ou grupo de outra organização; Conflict("already_set_up") quando a organização já tem um cadastro padrão criado com outra chave.
- **Efeitos:** cria o cadastro (privado, dono o ator), dá ao papel ``member`` leitura e alteração da tabela do cadastro, concede leitura e alteração aos grupos de escrita e leitura aos de leitura; tudo na transação do chamador. A mesma chave do mesmo ator devolve o cadastro já criado, sem repetir concessões.

#### `setup_steps(*, actor) -> tuple[SetupStepInfo, ...]`

The steps of the clinic setup list contributed by the active apps, in order, with their state.

- **Autorização:** a capacidade ``access.manage`` (administrador da organização).
- **Erros:** Forbidden sem a capacidade.
- **Efeitos:** nenhum.

#### `start_import(*, actor, stream, registry_id=None, idempotency_key) -> ImportStatus`

Upload a patient CSV into a registry; nothing is created until the batch is mapped and applied.

- **Autorização:** alteração no cadastro (o padrão quando não informado).
- **Erros:** NotFound para cadastro ilegível; Forbidden se só lê; InvalidInput("file") para arquivo acima de 10 MB, com mais de 20.000 linhas, vazio, sem cabeçalho ou que não é CSV (antes de gravar qualquer coisa).
- **Efeitos:** grava o lote (com o texto do arquivo, apagado quando o lote termina) e anexa o arquivo original; a mesma chave do mesmo ator devolve o lote já criado.

#### `summaries(*, actor, patient_ids) -> tuple[PatientSummary, ...]`

Summaries of up to 200 patients, in the order asked; the ones the actor does not read are left out.

- **Autorização:** leitura do cadastro de cada paciente.
- **Erros:** InvalidInput para mais de 200 identificadores ou identificador inválido.
- **Efeitos:** nenhum.

#### `summary(*, actor, patient_id) -> PatientSummary`

Code, display name, birth date and status of one patient.

- **Autorização:** leitura do cadastro do paciente.
- **Erros:** NotFound para paciente inexistente, de outra organização ou ilegível.
- **Efeitos:** nenhum.

#### `timeline(*, actor, patient_id, cursor=None, page_size=20) -> TimelinePage`

The patient timeline: items of the providers of active apps, newest first.

- **Autorização:** leitura do cadastro do paciente (e a de cada provedor).
- **Erros:** NotFound para paciente inexistente, de outra organização ou ilegível; InvalidInput para cursor ou tamanho de página inválidos.
- **Efeitos:** nenhum.

#### `update(*, actor, patient_id, changes, expected_revision) -> PatientInfo`

Change identification, contact or address fields of a patient, with CAS.

- **Autorização:** alteração no cadastro do paciente.
- **Erros:** NotFound; Forbidden se só lê; InvalidInput com o nome do campo; Conflict ("stale_revision", "processing_restricted", "anonymized", "integrity_conflict").
- **Efeitos:** grava só os campos que mudaram e publica ``med_patients.patient_updated``; sem mudança real, não grava nem publica.

#### `update_coverage(*, actor, coverage_id, data, expected_revision) -> CoverageInfo`

Replace the data of a health plan card, with CAS; marking it primary unmarks the others.

- **Autorização:** alteração no cadastro do paciente.
- **Erros:** NotFound; Forbidden; InvalidInput; Conflict("stale_revision", "processing_restricted", "anonymized").
- **Efeitos:** grava só os campos que mudaram; sem mudança real, não grava.

#### `update_guardian(*, actor, guardian_id, data, expected_revision) -> GuardianInfo`

Replace the data of a guardian, with CAS.

- **Autorização:** alteração no cadastro do paciente.
- **Erros:** NotFound; Forbidden; InvalidInput; Conflict("stale_revision", "processing_restricted", "anonymized").
- **Efeitos:** grava só os campos que mudaram; sem mudança real, não grava.

## DTOs

### `ConsentInfo`

| Campo | Tipo |
|---|---|
| `sysid` | `UUID` |
| `patient_id` | `UUID` |
| `purpose` | `str` |
| `status` | `str` |
| `granted_at` | `datetime` |
| `revoked_at` | `datetime | None` |
| `collected_via` | `str` |
| `term_version` | `str` |
| `evidence_note` | `str` |
| `revision` | `int` |

### `ConsentPurpose`

A purpose of data processing a patient may consent to (beyond care itself).

| Campo | Tipo |
|---|---|
| `code` | `str` |
| `label` | `Any` |
| `description` | `Any` |

### `ConsentPurposeInfo`

| Campo | Tipo |
|---|---|
| `code` | `str` |
| `label` | `str` |
| `description` | `str` |

### `CoverageInfo`

| Campo | Tipo |
|---|---|
| `sysid` | `UUID` |
| `patient_id` | `UUID` |
| `insurer_name` | `str` |
| `insurer_code` | `str` |
| `plan_name` | `str` |
| `card_number` | `str` |
| `holder_name` | `str` |
| `valid_until` | `date | None` |
| `is_primary` | `bool` |
| `revision` | `int` |

### `CoverageInput`

| Campo | Tipo |
|---|---|
| `insurer_name` | `str` |
| `card_number` | `str` |
| `insurer_code` | `str` |
| `plan_name` | `str` |
| `holder_name` | `str` |
| `valid_until` | `date | None` |
| `is_primary` | `bool` |

### `GuardianInfo`

| Campo | Tipo |
|---|---|
| `sysid` | `UUID` |
| `patient_id` | `UUID` |
| `name` | `str` |
| `relationship` | `str` |
| `cpf` | `str` |
| `phone` | `str` |
| `email` | `str` |
| `is_legal_representative` | `bool` |
| `is_financial_responsible` | `bool` |
| `notes` | `str` |
| `revision` | `int` |

### `GuardianInput`

| Campo | Tipo |
|---|---|
| `name` | `str` |
| `relationship` | `str` |
| `cpf` | `str` |
| `phone` | `str` |
| `email` | `str` |
| `is_legal_representative` | `bool` |
| `is_financial_responsible` | `bool` |
| `notes` | `str` |

### `ImportStatus`

A CSV import: counts and a report of (row, error code); never the cells.

| Campo | Tipo |
|---|---|
| `sysid` | `UUID` |
| `registry_id` | `UUID` |
| `status` | `str` |
| `filename` | `str` |
| `columns` | `tuple[str, ...]` |
| `mapping` | `tuple[tuple[str, str], ...]` |
| `total_rows` | `int` |
| `valid_rows` | `int` |
| `applied_rows` | `int` |
| `created_rows` | `int` |
| `skipped_rows` | `int` |
| `error_rows` | `int` |
| `report` | `tuple[tuple[int, str], ...]` |
| `error_code` | `str` |
| `revision` | `int` |
| `created_at` | `datetime` |
| `finished_at` | `datetime | None` |

### `PatientDataReport`

| Campo | Tipo |
|---|---|
| `patient` | `PatientInfo` |
| `guardians` | `tuple[GuardianInfo, ...]` |
| `coverages` | `tuple[CoverageInfo, ...]` |
| `consents` | `tuple[ConsentInfo, ...]` |
| `sections` | `tuple[ReportSection, ...]` |
| `generated_at` | `datetime` |

### `PatientInfo`

| Campo | Tipo |
|---|---|
| `sysid` | `UUID` |
| `registry_id` | `UUID` |
| `code` | `str` |
| `full_name` | `str` |
| `social_name` | `str` |
| `display_name` | `str` |
| `birth_date` | `date | None` |
| `sex` | `str` |
| `cpf` | `str` |
| `national_health_card` | `str` |
| `identity_document` | `str` |
| `mother_name` | `str` |
| `phone` | `str` |
| `phone_secondary` | `str` |
| `email` | `str` |
| `contact_preference` | `str` |
| `postal_code` | `str` |
| `street` | `str` |
| `number` | `str` |
| `complement` | `str` |
| `district` | `str` |
| `city` | `str` |
| `state` | `str` |
| `status` | `str` |
| `deceased_on` | `date | None` |
| `notes` | `str` |
| `processing_restricted` | `bool` |
| `anonymized_at` | `datetime | None` |
| `revision` | `int` |
| `updated_at` | `datetime` |
| `writable` | `bool` |
| `needs_guardian` | `bool` |

### `PatientInput`

The fields a person fills in to register a patient; ``full_name`` is the only required one.

| Campo | Tipo |
|---|---|
| `full_name` | `str` |
| `social_name` | `str` |
| `birth_date` | `date | None` |
| `sex` | `str` |
| `cpf` | `str` |
| `national_health_card` | `str` |
| `identity_document` | `str` |
| `mother_name` | `str` |
| `phone` | `str` |
| `phone_secondary` | `str` |
| `email` | `str` |
| `contact_preference` | `str` |
| `postal_code` | `str` |
| `street` | `str` |
| `number` | `str` |
| `complement` | `str` |
| `district` | `str` |
| `city` | `str` |
| `state` | `str` |
| `notes` | `str` |

### `PatientSection`

A tab or shortcut on the patient page; ``url_name`` receives ``org`` and ``patient_id``.

| Campo | Tipo |
|---|---|
| `code` | `str` |
| `label` | `Any` |
| `url_name` | `str` |
| `order` | `int` |
| `visible` | `Callable[..., bool] | None` |

### `PatientSectionInfo`

| Campo | Tipo |
|---|---|
| `code` | `str` |
| `label` | `str` |
| `url_name` | `str` |
| `order` | `int` |

### `PatientSummary`

What other apps show of a patient in a list: never contacts, documents or address.

| Campo | Tipo |
|---|---|
| `sysid` | `UUID` |
| `code` | `str` |
| `display_name` | `str` |
| `birth_date` | `date | None` |
| `status` | `str` |
| `revision` | `int` |
| `processing_restricted` | `bool` |

### `RegistryInfo`

| Campo | Tipo |
|---|---|
| `sysid` | `UUID` |
| `name` | `str` |
| `is_default` | `bool` |
| `revision` | `int` |
| `writable` | `bool` |

### `ReportSection`

One section of the data subject report: a title and (label, value) lines.

| Campo | Tipo |
|---|---|
| `code` | `str` |
| `title` | `str` |
| `lines` | `tuple[tuple[str, str], ...]` |
| `available` | `bool` |

### `SetupStep`

A step of the clinic setup list; ``is_done(actor=...)`` says whether it is complete.

| Campo | Tipo |
|---|---|
| `code` | `str` |
| `label` | `Any` |
| `url_name` | `str` |
| `is_done` | `Callable[..., bool]` |
| `order` | `int` |

### `SetupStepInfo`

| Campo | Tipo |
|---|---|
| `code` | `str` |
| `label` | `str` |
| `url_name` | `str` |
| `order` | `int` |
| `done` | `bool` |

### `TimelineEntry`

One item of the patient timeline. ``title`` never carries health data ("Consulta realizada").

| Campo | Tipo |
|---|---|
| `at` | `datetime` |
| `source` | `str` |
| `kind` | `str` |
| `title` | `str` |
| `url_name` | `str` |
| `url_args` | `tuple[str, ...]` |

### `TimelinePage`

A page of the timeline; ``unavailable`` lists the providers that failed (their items are missing).

| Campo | Tipo |
|---|---|
| `items` | `tuple[TimelineEntry, ...]` |
| `next_cursor` | `str | None` |
| `unavailable` | `tuple[str, ...]` |

<!-- END GENERATED -->

## Pontos de extensão

Funções reexportadas por este módulo, chamadas no `ready()` da app que se pluga. O código é `<app_label>.<nome>` da própria app chamadora; registrar o mesmo código com outro conteúdo é `ValueError`; a contribuição só aparece com a app dela ativa na organização.

| Função | Para quê |
|---|---|
| `register_consent_purpose(ConsentPurpose(code, label, description))` | Finalidade de consentimento LGPD |
| `register_retention_guard(code, guard)` | Veto à exclusão ou anonimização; `guard(patient_id=...)` devolve o motivo ou `None` e roda no contexto da organização do chamador. Uma guarda que falha também veta |
| `register_patient_section(PatientSection(code, label, url_name, order))` | Aba ou atalho na página do paciente; a rota recebe `org` e `patient_id` e autoriza sozinha |
| `register_timeline_provider(code, provider)` | Itens da linha do tempo: `provider(*, actor, patient_id, before, limit)` devolve até `limit` `TimelineEntry` com `at <= before` (ou os mais recentes, com `before=None`), já autorizados; o título nunca leva dado de saúde |
| `register_patient_data_provider(code, provider)` | Seção do relatório do titular: `provider(*, actor, patient_id)` devolve pares (rótulo, valor) |
| `register_setup_step(SetupStep(code, label, url_name, is_done, order))` | Passo da lista "Configuração da clínica"; `is_done(actor=...)` diz se está concluído |

Um provedor que levanta exceção não derruba a página: a falha vai para o log só com o código da contribuição e o tipo do erro, e a linha do tempo lista o provedor em `unavailable`.

## Eventos publicados

Payload dos eventos de paciente só com `code`, `status` e `registry` (o `sysid` do cadastro, em texto): nunca nome, documento, contato ou endereço.

| Tipo | Quando |
|---|---|
| `med_patients.patient_created` | `create` |
| `med_patients.patient_updated` | `update` com mudança real |
| `med_patients.patient_status_changed` | `set_status` com mudança real |
| `med_patients.consent_changed` | `grant_consent` e `revoke_consent`; payload `patient`, `purpose`, `status` |

## Histórico de versões
| Versão | Mudança |
|---|---|
| 0.1.0 | Primeira versão |
