# API de serviços: Pacientes

Referência de `PatientService` (`applications.med_patients.service_api`). O contrato geral está na [API de serviços do núcleo](https://github.com/alaorneto/skeleton/blob/f38c9a02166d63e402d2c7708e616ae842441665/docs/service-api.md).

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

### `RegistryInfo`

| Campo | Tipo |
|---|---|
| `sysid` | `UUID` |
| `name` | `str` |
| `is_default` | `bool` |
| `revision` | `int` |
| `writable` | `bool` |

<!-- END GENERATED -->

## Pontos de extensão

Funções reexportadas por este módulo, chamadas no `ready()` da app que se pluga. O código é `<app_label>.<nome>` da própria app chamadora; registrar o mesmo código com outro conteúdo é `ValueError`; a contribuição só aparece com a app dela ativa na organização.

| Função | Para quê |
|---|---|
| `register_consent_purpose(ConsentPurpose(code, label, description))` | Finalidade de consentimento LGPD |
| `register_retention_guard(code, guard)` | Veto à exclusão ou anonimização; `guard(patient_id=...)` devolve o motivo ou `None` e roda no contexto da organização do chamador |

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
