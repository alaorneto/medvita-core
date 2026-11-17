# API de serviços: Pacientes

Referência de `PatientService` (`applications.med_patients.service_api`). O contrato geral está na [API de serviços do núcleo](https://github.com/alaorneto/skeleton/blob/f38c9a02166d63e402d2c7708e616ae842441665/docs/service-api.md).

## Visão geral

`PatientService` dá às outras apps e às superfícies desta app o cadastro de pacientes da organização atual, com a autorização do ator do contexto. Todos os métodos exigem a app ativa (`Unavailable`), contexto de organização aberto pelo chamador e `actor` igual ao ator do contexto (`Forbidden`). Comandos rodam num savepoint da transação do chamador.

## Dependência

`app_id`: `io.katua.sk.med.patients`. Faixa no manifesto do consumidor: a versão corrente da suíte, `>=0.1.0,<0.2.0` na primeira linha. Importe só o módulo `service_api` desta app.

## Serviços

### `PatientService`

#### `setup(*, actor, name, writer_group_ids=(), reader_group_ids=(), idempotency_key) -> RegistryInfo`
- **Autorização:** capacidade `access.manage` e `create` em `med_patients.patientregistry`.
- **Erros:** `Forbidden`; `InvalidInput` (nome vazio, chave inválida, mais de 20 grupos, grupo de outra organização); `Conflict("already_set_up")` quando já existe cadastro padrão criado com outra chave.
- **Efeitos:** cria o cadastro padrão privado do ator; dá ao papel `member` `read` e `update` na tabela do cadastro; concede `read` e `update` aos grupos de escrita e `read` aos de leitura. A mesma chave do mesmo ator devolve o cadastro já criado.

#### `registries(*, actor) -> tuple[RegistryInfo, ...]`
- **Autorização:** `read` na tabela e em cada cadastro.
- **Erros:** `Forbidden` sem a permissão de tabela.
- **Efeitos:** nenhum.

## DTOs

### `RegistryInfo`
| Campo | Tipo | Significado |
|---|---|---|
| `sysid` | UUID | Identificador do cadastro |
| `name` | str | Nome |
| `is_default` | bool | Cadastro padrão da organização |
| `revision` | int | Revisão atual |
| `writable` | bool | O ator altera o cadastro (e os pacientes dele) |

## Eventos publicados

Nenhum nesta versão.

## Histórico de versões
| Versão | Mudança |
|---|---|
| 0.1.0 | Primeira versão |
