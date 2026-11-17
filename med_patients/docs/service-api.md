# API de serviços: Pacientes

Referência gerada por `skeleton_startapp`. Mantenha-a junto com `service_api.py`: o check E012 exige este arquivo com as seções abaixo e o E018 confere a classe declarada no manifesto. O contrato geral está em [docs/service-api.md](../../../docs/service-api.md).

## Visão geral
`PatientRegistryService` oferece a outras apps consultas de `PatientRegistry` da organização atual, com a autorização do ator do contexto. A página própria e o sumário REST desta app usam o mesmo serviço.

## Dependência
`app_id`: `io.katua.sk.med.patients`. Faixa recomendada no manifesto do consumidor: `{"io.katua.sk.med.patients": ">=0.1.0,<1.0.0"}`. Importe só o módulo `service_api` desta app.

## Serviços

### `PatientRegistryService`
Todos os métodos exigem a app ativa (`Unavailable`), contexto tenant aberto pelo chamador e `actor` igual ao ator do contexto (`Forbidden`).

#### `patientregistry_count(*, actor) -> int`
- **Autorização:** read em `med_patients.patientregistry`; conta só registros legíveis.
- **Erros:** `Forbidden`; `Unavailable`.
- **Efeitos:** nenhum.

#### `list_patientregistry_summaries(*, actor, cursor=None, page_size=25) -> Page[PatientRegistrySummary]`
- **Autorização:** read em `med_patients.patientregistry`; filtra antes de paginar.
- **Erros:** `InvalidInput` para cursor ou `page_size` fora de 1..100; `Forbidden`; `Unavailable`.
- **Efeitos:** nenhum.

#### `get_patientregistry(*, actor, record_id) -> PatientRegistrySummary`
- **Autorização:** read na tabela e acesso de leitura ao registro.
- **Erros:** `NotFound` para inexistente, de outra organização ou não legível; `Forbidden`; `Unavailable`.
- **Efeitos:** nenhum.

## DTOs

### `PatientRegistrySummary`
| Campo | Tipo | Significado |
|---|---|---|
| `sysid` | UUID | Identificador estável |
| `code` | str | Código único entre registros vivos da organização |
| `title` | str | Título |
| `revision` | int | Revisão atual |
| `updated_at` | datetime (UTC) | Última alteração |

## Eventos publicados
Não se aplica.

## Histórico de versões
| Versão | Mudança |
|---|---|
| 0.1.0 | Primeira versão: `patientregistry_count`, `list_patientregistry_summaries`, `get_patientregistry` |
