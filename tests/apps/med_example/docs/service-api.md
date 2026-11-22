# API de serviços: Exemplo de extensão

## Visão geral

`ExampleService` grava e lê notas sobre pacientes e cobra pelo financeiro como origem de conta.

## Dependência

`app_id`: `io.medvita.example`. Só para os testes.

## Serviços

### `ExampleService`

`setup`, `notes`, `add_note` e `bill`; as docstrings trazem autorização, erros e efeitos.

## DTOs

`NoteInfo`: `sysid`, `patient_id`, `source`, `text`, `keep`.

## Histórico de versões
| Versão | Mudança |
|---|---|
| 0.1.0 | Primeira versão |
