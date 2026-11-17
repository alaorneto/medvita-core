# API de serviços: Agenda médica

Referência gerada por `skeleton_startapp`. Mantenha-a junto com `service_api.py`: o check E012 exige este arquivo com as seções abaixo e o E018 confere a classe declarada no manifesto. O contrato geral está em [docs/service-api.md](https://github.com/alaorneto/skeleton/blob/f38c9a02166d63e402d2c7708e616ae842441665/docs/service-api.md).

## Visão geral
`PracticeService` oferece a outras apps consultas de `Practice` da organização atual, com a autorização do ator do contexto. A página própria e o sumário REST desta app usam o mesmo serviço.

## Dependência
`app_id`: `io.katua.sk.med.scheduling`. Faixa recomendada no manifesto do consumidor: `{"io.katua.sk.med.scheduling": ">=0.1.0,<1.0.0"}`. Importe só o módulo `service_api` desta app.

## Serviços

### `PracticeService`
Todos os métodos exigem a app ativa (`Unavailable`), contexto tenant aberto pelo chamador e `actor` igual ao ator do contexto (`Forbidden`).

#### `practice_count(*, actor) -> int`
- **Autorização:** read em `med_scheduling.practice`; conta só registros legíveis.
- **Erros:** `Forbidden`; `Unavailable`.
- **Efeitos:** nenhum.

#### `list_practice_summaries(*, actor, cursor=None, page_size=25) -> Page[PracticeSummary]`
- **Autorização:** read em `med_scheduling.practice`; filtra antes de paginar.
- **Erros:** `InvalidInput` para cursor ou `page_size` fora de 1..100; `Forbidden`; `Unavailable`.
- **Efeitos:** nenhum.

#### `get_practice(*, actor, record_id) -> PracticeSummary`
- **Autorização:** read na tabela e acesso de leitura ao registro.
- **Erros:** `NotFound` para inexistente, de outra organização ou não legível; `Forbidden`; `Unavailable`.
- **Efeitos:** nenhum.

## DTOs

### `PracticeSummary`
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
| 0.1.0 | Primeira versão: `practice_count`, `list_practice_summaries`, `get_practice` |
