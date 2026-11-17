# API de serviços: Prontuário

Referência de `RecordsService` (`applications.med_records.service_api`). O contrato geral está na [API de serviços do núcleo](https://github.com/alaorneto/skeleton/blob/f38c9a02166d63e402d2c7708e616ae842441665/docs/service-api.md).

## Visão geral

`RecordsService` dá às outras apps e às superfícies desta app os arquivos clínicos, os prontuários e, nas versões seguintes, os atendimentos e documentos, com a autorização do ator do contexto. Todos os métodos exigem a app ativa (`Unavailable`), contexto de organização e `actor` igual ao do contexto. Comandos rodam num savepoint da transação do chamador. Registro inexistente, de outra organização ou ilegível respondem o mesmo `NotFound`.

## Dependência

`app_id`: `io.katua.sk.med.records`. Faixa no manifesto do consumidor: a versão corrente da suíte, `>=0.1.0,<0.2.0` na primeira linha. Importe só o módulo `service_api` desta app.

<!-- BEGIN GENERATED: tools/service_reference.py -->

## Serviços

### `RecordsService`

#### `archives(*, actor) -> tuple[ArchiveInfo, ...]`

The clinical archives the actor reads, the default first.

- **Autorização:** leitura de cada arquivo.
- **Erros:** nenhum além do contrato.
- **Efeitos:** nenhum.

#### `chart(*, actor, chart_id) -> ChartInfo`

One chart, without clinical content.

- **Autorização:** leitura do arquivo.
- **Erros:** NotFound para prontuário inexistente, de outra organização ou ilegível.
- **Efeitos:** nenhum.

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

#### `open_chart(*, actor, patient_id, archive_id=None, idempotency_key=None) -> ChartInfo`

The chart of the patient in the archive, created on first use (get or create).

- **Autorização:** alteração no arquivo e leitura do paciente.
- **Erros:** NotFound para paciente ou arquivo ilegíveis; Forbidden sem alteração no arquivo; InvalidInput quando o ator altera vários arquivos e nenhum é o padrão.
- **Efeitos:** cria o prontuário uma vez; repetir devolve o mesmo.

#### `setup(*, actor, mode='shared', name='', member_group_ids=(), idempotency_key) -> tuple[ArchiveInfo, ...]`

Create the first clinical archives of the organization.

- **Autorização:** a capacidade ``access.manage`` e ``create`` em med_records.archive.
- **Erros:** Forbidden; InvalidInput para modo desconhecido, nome inválido, mais de 20 grupos ou nenhum profissional vinculado; Conflict("already_set_up") com arquivos criados por outra chave.
- **Efeitos:** cria os arquivos (privados), dá ao papel ``member`` leitura e alteração da tabela de arquivos e concede leitura e alteração aos grupos. A mesma chave devolve o já criado.

## DTOs

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

### `DocumentKind`

A kind of clinical document. ``default_body`` may use {{patient_name}}, {{date}}, {{professional_name}}.

| Campo | Tipo |
|---|---|
| `code` | `str` |
| `label` | `Any` |
| `default_body` | `Any` |
| `notice` | `Any` |

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

### `SectionType`

A structured section of an encounter: its fields, version and whether it takes free text.

| Campo | Tipo |
|---|---|
| `code` | `str` |
| `label` | `Any` |
| `fields` | `tuple[SectionField, ...]` |
| `version` | `int` |
| `has_text` | `bool` |

<!-- END GENERATED -->

## Contribuições a outras apps

Registradas no `ready()`: a guarda de retenção `med_records.retention` e o passo de configuração `med_records.archives` de `med_patients`.

## Histórico de versões
| Versão | Mudança |
|---|---|
| 0.1.0 | Primeira versão |
