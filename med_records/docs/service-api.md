# API de serviços: Prontuário

Referência de `RecordsService` (`applications.med_records.service_api`). O contrato geral está na [API de serviços do núcleo](https://github.com/alaorneto/skeleton/blob/f38c9a02166d63e402d2c7708e616ae842441665/docs/service-api.md).

## Visão geral

`RecordsService` dá às outras apps e às superfícies desta app os arquivos clínicos, os prontuários e, nas versões seguintes, os atendimentos e documentos, com a autorização do ator do contexto. Todos os métodos exigem a app ativa (`Unavailable`), contexto de organização e `actor` igual ao do contexto. Comandos rodam num savepoint da transação do chamador. Registro inexistente, de outra organização ou ilegível respondem o mesmo `NotFound`.

## Dependência

`app_id`: `io.katua.sk.med.records`. Faixa no manifesto do consumidor: a versão corrente da suíte, `>=0.1.0,<0.2.0` na primeira linha. Importe só o módulo `service_api` desta app.

<!-- BEGIN GENERATED: tools/service_reference.py -->

## Serviços

### `RecordsService`

#### `access_log(*, actor, chart_id, cursor=None, page_size=50) -> Page[AccessLogEntry]`

Who read clinical content of the chart, newest first.

- **Autorização:** gestão de acesso do arquivo (dono ou administrador); quem só lê ou escreve o prontuário não lê a trilha.
- **Erros:** NotFound para prontuário ilegível; Forbidden sem gestão de acesso.
- **Efeitos:** nenhum.

#### `add_addendum(*, actor, encounter_id, text, idempotency_key) -> EncounterInfo`

Start a draft addendum (free text) to a signed encounter; it is signed by ``sign_encounter``.

- **Autorização:** alteração no arquivo do atendimento.
- **Erros:** NotFound; Forbidden; Conflict("not_signed") para atendimento não assinado ou que já é um adendo; InvalidInput para texto vazio ou longo demais.
- **Efeitos:** cria o rascunho do adendo com uma seção de texto livre.

#### `add_allergy(*, actor, chart_id, substance, category='other', reaction='', severity='unknown', noted_on=None, idempotency_key) -> AllergyInfo`

Record an allergy on the chart.

- **Autorização:** alteração no arquivo do prontuário.
- **Erros:** NotFound; Forbidden; InvalidInput com o nome do campo.
- **Efeitos:** grava a alergia (substância e reação são dado de saúde) e o último registro do prontuário. A mesma chave devolve a já gravada.

#### `add_medication(*, actor, chart_id, name, dose='', route='', frequency='', started_on=None, note='', idempotency_key) -> MedicationInfo`

Record a medication in use on the chart.

- **Autorização:** alteração no arquivo do prontuário.
- **Erros:** NotFound; Forbidden; InvalidInput com o nome do campo.
- **Efeitos:** grava o medicamento (dado de saúde) e o último registro do prontuário. A mesma chave devolve o já gravado.

#### `allergies(*, actor, chart_id) -> tuple[AllergyInfo, ...]`

The allergies of the chart, active first, severe before the others.

- **Autorização:** leitura do arquivo do prontuário.
- **Erros:** NotFound para prontuário ilegível.
- **Efeitos:** registra a leitura na trilha do prontuário.

#### `archives(*, actor) -> tuple[ArchiveInfo, ...]`

The clinical archives the actor reads, the default first.

- **Autorização:** leitura de cada arquivo.
- **Erros:** nenhum além do contrato.
- **Efeitos:** nenhum.

#### `attach_to_chart(*, actor, chart_id, filename, stream, content_type=None) -> AttachmentInfo`

Attach an exam or external document (PDF, JPEG, PNG, up to 20 MB) to the chart.

- **Autorização:** alteração no arquivo do prontuário.
- **Erros:** NotFound; Forbidden; InvalidInput para tipo ou tamanho recusados.
- **Efeitos:** grava o anexo no armazenamento privado do núcleo e o último registro do prontuário.

#### `attach_to_encounter(*, actor, encounter_id, filename, stream, content_type=None) -> AttachmentInfo`

Attach a file to a draft encounter; the seal covers it once signed.

- **Autorização:** alteração no arquivo do atendimento.
- **Erros:** NotFound; Forbidden; Conflict("signed") para atendimento assinado (anexe ao prontuário); InvalidInput para tipo ou tamanho recusados.
- **Efeitos:** grava o anexo.

#### `attachment_url(*, actor, attachment_id, chart_id=None, encounter_id=None) -> str`

The authorized download address of an attachment of the chart or encounter; recorded in the trail.

- **Autorização:** leitura do arquivo (o download é reautorizado pelo núcleo a cada requisição).
- **Erros:** NotFound para anexo de outro registro, ilegível ou indisponível; InvalidInput sem alvo.
- **Efeitos:** registra o download na trilha do prontuário.

#### `attachments(*, actor, chart_id=None, encounter_id=None) -> tuple[AttachmentInfo, ...]`

The attachments of a chart or of an encounter (exactly one of the two).

- **Autorização:** leitura do arquivo.
- **Erros:** NotFound; InvalidInput sem alvo ou com os dois.
- **Efeitos:** nenhum.

#### `chart(*, actor, chart_id) -> ChartInfo`

One chart, without clinical content.

- **Autorização:** leitura do arquivo.
- **Erros:** NotFound para prontuário inexistente, de outra organização ou ilegível.
- **Efeitos:** nenhum.

#### `chart_summary(*, actor, chart_id) -> ChartSummary`

Active allergies (severe first), medications in use and the five latest encounter headers.

- **Autorização:** leitura do arquivo do prontuário.
- **Erros:** NotFound para prontuário ilegível.
- **Efeitos:** registra a leitura na trilha do prontuário.

#### `charts_for_patient(*, actor, patient_id) -> tuple[ChartInfo, ...]`

The charts of a patient in the archives the actor reads.

- **Autorização:** leitura de cada arquivo; o paciente não é conferido (sem arquivo legível, vazio).
- **Erros:** InvalidInput para identificador inválido.
- **Efeitos:** nenhum.

#### `create_archive(*, actor, name, kind='shared', owner_user_id=None, writer_group_ids=(), writer_user_ids=(), idempotency_key) -> ArchiveInfo`

Create one more clinical archive, written by the groups and people informed.

- **Autorização:** a capacidade ``access.manage`` e ``create`` em med_records.archive.
- **Erros:** Forbidden; InvalidInput para nome ou tipo inválidos, dono que não é membro ativo ou listas longas demais.
- **Efeitos:** cria o arquivo privado (dono ``owner_user_id`` ou o ator) e concede leitura e alteração aos grupos e pessoas. A mesma chave devolve o já criado.

#### `create_template(*, actor, name, kind, archive_id=None, specialty='', sections=(), document_kind='', body='', personal=False, idempotency_key) -> TemplateInfo`

Create a template of encounter sections or of a document, shared in the archive or personal.

- **Autorização:** alteração no arquivo (o padrão que o ator altera, sem ``archive_id``).
- **Erros:** NotFound; Forbidden; InvalidInput para nome, tipo, seções ou tipo de documento inválidos.
- **Efeitos:** grava o modelo; pessoal, só o autor o vê e altera. A mesma chave devolve o já criado.

#### `discard_draft(*, actor, encounter_id, expected_revision) -> None`

Discard the actor's draft encounter with its sections.

- **Autorização:** alteração no arquivo; só o autor do rascunho.
- **Erros:** NotFound; Forbidden; Conflict("signed") para atendimento assinado; Conflict("stale_revision").
- **Efeitos:** exclusão lógica das seções e do atendimento.

#### `document(*, actor, document_id) -> DocumentInfo`

One document with its text; the read is recorded in the trail.

- **Autorização:** leitura do arquivo do prontuário.
- **Erros:** NotFound para documento inexistente, de outra organização ou ilegível.
- **Efeitos:** registra a leitura na trilha do prontuário.

#### `documents(*, actor, chart_id) -> tuple[DocumentHeader, ...]`

Headers of the chart's documents, newest first, without their text.

- **Autorização:** leitura do arquivo do prontuário.
- **Erros:** NotFound para prontuário ilegível.
- **Efeitos:** nenhum.

#### `draft_document(*, actor, chart_id, kind, title='', body=None, encounter_id=None, template_id=None, idempotency_key) -> DocumentInfo`

Start a draft document written by the actor, from the kind's default text or a template.

- **Autorização:** alteração no arquivo do prontuário.
- **Erros:** NotFound; Forbidden; InvalidInput para tipo desconhecido, modelo de outro tipo, atendimento de outro prontuário ou texto longo demais.
- **Efeitos:** cria o rascunho com o código da sequência e atualiza o último registro do prontuário. A mesma chave devolve o mesmo rascunho.

#### `encounter(*, actor, encounter_id) -> EncounterInfo`

One encounter with its sections and signed addenda; the read is recorded in the trail.

- **Autorização:** leitura do arquivo do prontuário.
- **Erros:** NotFound para atendimento inexistente, de outra organização ou ilegível.
- **Efeitos:** registra a leitura na trilha do prontuário.

#### `encounters(*, actor, chart_id, cursor=None, page_size=50) -> Page[EncounterHeader]`

Headers of the chart's encounters, newest first, without clinical content.

- **Autorização:** leitura do arquivo do prontuário.
- **Erros:** NotFound para prontuário ilegível; InvalidInput para cursor ou tamanho inválidos.
- **Efeitos:** nenhum.

#### `issue_document(*, actor, document_id, expected_revision) -> DocumentInfo`

Issue the actor's draft document: photograph the author, seal it and publish ``document_issued``.

- **Autorização:** alteração no arquivo; só o autor do rascunho.
- **Erros:** NotFound; Forbidden; Conflict("empty") sem texto; Conflict("professional_required") sem ficha de profissional com conselho; Conflict("issued") ou Conflict("stale_revision").
- **Efeitos:** grava data de emissão, nome e conselho, sela e publica o evento (sem título nem texto).

#### `medications(*, actor, chart_id) -> tuple[MedicationInfo, ...]`

The medications of the chart, in use first.

- **Autorização:** leitura do arquivo do prontuário.
- **Erros:** NotFound para prontuário ilegível.
- **Efeitos:** registra a leitura na trilha do prontuário.

#### `open_chart(*, actor, patient_id, archive_id=None, idempotency_key=None) -> ChartInfo`

The chart of the patient in the archive, created on first use (get or create).

- **Autorização:** alteração no arquivo e leitura do paciente.
- **Erros:** NotFound para paciente ou arquivo ilegíveis; Forbidden sem alteração no arquivo; InvalidInput quando o ator altera vários arquivos e nenhum é o padrão.
- **Efeitos:** cria o prontuário uma vez; repetir devolve o mesmo.

#### `remove_section(*, actor, encounter_id, section_id, expected_revision) -> EncounterInfo`

Remove one section of the actor's draft.

- **Autorização:** alteração no arquivo; só o autor do rascunho.
- **Erros:** NotFound; Forbidden; Conflict("signed") ou Conflict("stale_revision").
- **Efeitos:** exclusão lógica da seção e nova revisão do atendimento.

#### `replace_document(*, actor, document_id, idempotency_key) -> DocumentInfo`

Start a draft that replaces an issued document, with the same kind, title and text.

- **Autorização:** alteração no arquivo do documento.
- **Erros:** NotFound; Forbidden; Conflict("not_issued") para documento em rascunho.
- **Efeitos:** cria o rascunho com ``replaces``. A mesma chave devolve o mesmo rascunho.

#### `save_section(*, actor, encounter_id, section_type, data=(), text='', position=0, expected_revision) -> EncounterInfo`

Write one section of the actor's draft (the section at ``section_type`` and ``position``).

- **Autorização:** alteração no arquivo; só o autor do rascunho.
- **Erros:** NotFound; Forbidden para quem não é o autor; InvalidInput para tipo desconhecido ou campo inválido (citado pelo nome); Conflict("signed") ou Conflict("stale_revision").
- **Efeitos:** grava a seção, sobe a revisão do atendimento e o último registro do prontuário.

#### `search_icd10(*, actor, query, limit=20) -> tuple[Icd10Info, ...]`

ICD-10 codes by code prefix (``J45``) or by the words of the description (``asma``).

- **Autorização:** qualquer ator da organização com a app ativa (o catálogo é público e global).
- **Erros:** InvalidInput para busca vazia ou longa demais, ou limite fora de 1 a 50.
- **Efeitos:** nenhum.

#### `setup(*, actor, mode='shared', name='', member_group_ids=(), idempotency_key) -> tuple[ArchiveInfo, ...]`

Create the first clinical archives of the organization.

- **Autorização:** a capacidade ``access.manage`` e ``create`` em med_records.archive.
- **Erros:** Forbidden; InvalidInput para modo desconhecido, nome inválido, mais de 20 grupos ou nenhum profissional vinculado; Conflict("already_set_up") com arquivos criados por outra chave.
- **Efeitos:** cria os arquivos (privados), dá ao papel ``member`` leitura e alteração da tabela de arquivos e concede leitura e alteração aos grupos. A mesma chave devolve o já criado.

#### `sign_encounter(*, actor, encounter_id, expected_revision) -> EncounterInfo`

Sign the actor's draft: photograph the author, seal it and publish ``encounter_signed``.

- **Autorização:** alteração no arquivo; só o autor do rascunho.
- **Erros:** NotFound; Forbidden; Conflict("empty") sem seção com conteúdo; Conflict("professional_required") sem ficha de profissional com conselho na agenda; Conflict("signed") ou Conflict("stale_revision").
- **Efeitos:** grava nome e conselho do autor, sela o atendimento com as seções e publica o evento.

#### `start_encounter(*, actor, chart_id, kind='consultation', occurred_at=None, appointment_id=None, template_id=None, idempotency_key) -> EncounterInfo`

Start a draft encounter written by the actor; with an arrived appointment, start the attendance.

- **Autorização:** alteração no arquivo do prontuário; com ``appointment_id``, leitura da consulta.
- **Erros:** NotFound para prontuário ou consulta ilegíveis; Forbidden sem alteração no arquivo; InvalidInput para tipo desconhecido (o adendo nasce por ``add_addendum``), data futura, consulta de outro paciente ou modelo que não é de atendimento.
- **Efeitos:** cria o rascunho com o código da sequência (e as seções do modelo) e atualiza o último registro do prontuário; com a consulta em "chegou", tenta iniciá-la na agenda (recusa da agenda não impede o rascunho). A mesma chave devolve o mesmo rascunho.

#### `templates(*, actor, archive_id=None, kind=None, active_only=True) -> tuple[TemplateInfo, ...]`

Templates of the archives the actor reads: the shared ones and the actor's personal ones.

- **Autorização:** leitura do arquivo; modelos pessoais de outra pessoa nunca aparecem.
- **Erros:** InvalidInput para tipo desconhecido ou identificador inválido.
- **Efeitos:** nenhum.

#### `update_allergy(*, actor, allergy_id, changes, expected_revision) -> AllergyInfo`

Change an allergy (its status, for example), with CAS; the audit keeps the history (redacted).

- **Autorização:** alteração no arquivo do prontuário.
- **Erros:** NotFound; Forbidden; InvalidInput com o nome do campo; Conflict("stale_revision").
- **Efeitos:** grava só os campos que mudaram.

#### `update_document(*, actor, document_id, title, body, expected_revision) -> DocumentInfo`

Change the title and text of the actor's draft document, with CAS.

- **Autorização:** alteração no arquivo; só o autor do rascunho.
- **Erros:** NotFound; Forbidden; InvalidInput; Conflict("issued") ou Conflict("stale_revision").
- **Efeitos:** grava o que mudou.

#### `update_medication(*, actor, medication_id, changes, expected_revision) -> MedicationInfo`

Change a medication (suspend or end it, for example), with CAS.

- **Autorização:** alteração no arquivo do prontuário.
- **Erros:** NotFound; Forbidden; InvalidInput com o nome do campo; Conflict("stale_revision").
- **Efeitos:** grava só os campos que mudaram.

#### `update_template(*, actor, template_id, expected_revision, name=None, specialty=None, sections=None, body=None, active=None) -> TemplateInfo`

Change a template (or deactivate it), with CAS; a personal template only by its author.

- **Autorização:** alteração no arquivo; modelo pessoal, só o autor.
- **Erros:** NotFound (inclusive modelo pessoal de outra pessoa); Forbidden; InvalidInput; Conflict("stale_revision").
- **Efeitos:** grava só o que mudou.

#### `verify_document(*, actor, document_id) -> SealCheck`

Recompute the seal of a document from the stored content.

- **Autorização:** leitura do arquivo do prontuário.
- **Erros:** NotFound para documento inexistente, de outra organização ou ilegível.
- **Efeitos:** nenhum.

#### `verify_encounter(*, actor, encounter_id) -> SealCheck`

Recompute the seal of an encounter from the stored content and its sections.

- **Autorização:** leitura do arquivo do atendimento.
- **Erros:** NotFound para atendimento inexistente, de outra organização ou ilegível.
- **Efeitos:** nenhum.

## DTOs

### `AccessLogEntry`

| Campo | Tipo |
|---|---|
| `sysid` | `UUID` |
| `actor_id` | `UUID` |
| `action` | `str` |
| `target_table` | `str` |
| `target_id` | `UUID | None` |
| `at` | `datetime` |

### `AllergyInfo`

| Campo | Tipo |
|---|---|
| `sysid` | `UUID` |
| `chart_id` | `UUID` |
| `substance` | `str` |
| `category` | `str` |
| `reaction` | `str` |
| `severity` | `str` |
| `status` | `str` |
| `noted_on` | `date | None` |
| `revision` | `int` |

### `ArchiveInfo`

| Campo | Tipo |
|---|---|
| `sysid` | `UUID` |
| `name` | `str` |
| `kind` | `str` |
| `is_default` | `bool` |
| `revision` | `int` |
| `writable` | `bool` |

### `ChartInfo`

A chart without clinical content: which patient, which archive, when it was last written.

| Campo | Tipo |
|---|---|
| `sysid` | `UUID` |
| `archive_id` | `UUID` |
| `patient_id` | `UUID` |
| `opened_at` | `datetime` |
| `last_entry_at` | `datetime | None` |
| `revision` | `int` |
| `writable` | `bool` |

### `ChartSummary`

What the chart page shows first (clinical content: the read is recorded in the trail).

| Campo | Tipo |
|---|---|
| `chart` | `ChartInfo` |
| `allergies` | `tuple[AllergyInfo, ...]` |
| `medications` | `tuple[MedicationInfo, ...]` |
| `latest` | `tuple[EncounterHeader, ...]` |

### `DocumentHeader`

A clinical document without its text: what lists show.

| Campo | Tipo |
|---|---|
| `sysid` | `UUID` |
| `chart_id` | `UUID` |
| `patient_id` | `UUID` |
| `code` | `str` |
| `kind` | `str` |
| `title` | `str` |
| `issued` | `bool` |
| `issued_at` | `datetime | None` |
| `author_id` | `UUID` |
| `author_name` | `str` |
| `author_council` | `str` |
| `encounter_id` | `UUID | None` |
| `replaces_id` | `UUID | None` |
| `replaced_by_code` | `str` |
| `seal_digest` | `str` |
| `revision` | `int` |

### `DocumentInfo`

A clinical document with its text (clinical content: the read is recorded in the trail).

| Campo | Tipo |
|---|---|
| `header` | `DocumentHeader` |
| `body` | `str` |
| `notice` | `str` |
| `writable` | `bool` |

### `DocumentKind`

A kind of clinical document. ``default_body`` may use {{patient_name}}, {{date}}, {{professional_name}}.

| Campo | Tipo |
|---|---|
| `code` | `str` |
| `label` | `Any` |
| `default_body` | `Any` |
| `notice` | `Any` |

### `EncounterHeader`

An encounter without clinical content: what lists show.

| Campo | Tipo |
|---|---|
| `sysid` | `UUID` |
| `chart_id` | `UUID` |
| `patient_id` | `UUID` |
| `code` | `str` |
| `kind` | `str` |
| `occurred_at` | `datetime` |
| `author_id` | `UUID` |
| `author_name` | `str` |
| `author_council` | `str` |
| `appointment_id` | `UUID | None` |
| `amends_id` | `UUID | None` |
| `signed` | `bool` |
| `signed_at` | `datetime | None` |
| `seal_digest` | `str` |
| `revision` | `int` |

### `EncounterInfo`

An encounter with its sections (clinical content: every read is recorded in the trail).

| Campo | Tipo |
|---|---|
| `header` | `EncounterHeader` |
| `sections` | `tuple[SectionInfo, ...]` |
| `addenda` | `tuple[EncounterHeader, ...]` |
| `writable` | `bool` |
| `appointment_completed` | `bool` |

### `Icd10Info`

| Campo | Tipo |
|---|---|
| `code` | `str` |
| `description` | `str` |
| `is_category` | `bool` |

### `MedicationInfo`

| Campo | Tipo |
|---|---|
| `sysid` | `UUID` |
| `chart_id` | `UUID` |
| `name` | `str` |
| `dose` | `str` |
| `route` | `str` |
| `frequency` | `str` |
| `started_on` | `date | None` |
| `ended_on` | `date | None` |
| `status` | `str` |
| `note` | `str` |
| `revision` | `int` |

### `SealCheck`

Whether a record is signed and whether its stored content still matches the seal.

| Campo | Tipo |
|---|---|
| `sysid` | `UUID` |
| `signed` | `bool` |
| `valid` | `bool` |
| `seal_digest` | `str` |
| `signed_at` | `datetime | None` |

### `SectionField`

One structured field of a section type. ``choices`` are ``(code, label)`` pairs.

| Campo | Tipo |
|---|---|
| `name` | `str` |
| `label` | `Any` |
| `kind` | `str` |
| `required` | `bool` |
| `unit` | `str` |
| `min` | `float | None` |
| `max` | `float | None` |
| `choices` | `tuple[tuple[str, Any], ...]` |

### `SectionInfo`

A section with its content; ``data_json`` is the structured data as canonical JSON text.

| Campo | Tipo |
|---|---|
| `sysid` | `UUID` |
| `section_type` | `str` |
| `type_version` | `int` |
| `position` | `int` |
| `data_json` | `str` |
| `text` | `str` |

### `SectionType`

A structured section of an encounter: its fields, version and whether it takes free text.

| Campo | Tipo |
|---|---|
| `code` | `str` |
| `label` | `Any` |
| `fields` | `tuple[SectionField, ...]` |
| `version` | `int` |
| `has_text` | `bool` |

### `TemplateInfo`

| Campo | Tipo |
|---|---|
| `sysid` | `UUID` |
| `archive_id` | `UUID` |
| `name` | `str` |
| `specialty` | `str` |
| `kind` | `str` |
| `sections_json` | `str` |
| `document_kind` | `str` |
| `body` | `str` |
| `personal` | `bool` |
| `is_active` | `bool` |
| `revision` | `int` |

### `TemplateSectionInput`

One section of an encounter template: ``data`` are ``(field, value)`` pairs.

| Campo | Tipo |
|---|---|
| `section_type` | `str` |
| `text` | `str` |
| `data` | `tuple[tuple[str, Any], ...]` |

<!-- END GENERATED -->

## Contribuições a outras apps

Registradas no `ready()`: a guarda de retenção `med_records.retention` e o passo de configuração `med_records.archives` de `med_patients`.

## Histórico de versões
| Versão | Mudança |
|---|---|
| 0.1.0 | Primeira versão |
