# API de serviços: Financeiro

Referência de `FinanceService` (`applications.med_finance.service_api`). O contrato geral está na [API de serviços do núcleo](https://github.com/alaorneto/skeleton/blob/f38c9a02166d63e402d2c7708e616ae842441665/docs/service-api.md).

## Visão geral

`FinanceService` dá às outras apps e às superfícies desta app os preços, os caixas, as contas, os pagamentos e os recibos da organização atual, com a autorização do ator do contexto. Todos os métodos exigem a app ativa (`Unavailable`), contexto de organização e `actor` igual ao do contexto. Comandos rodam num savepoint da transação do chamador. Registro inexistente, de outra organização ou ilegível respondem o mesmo `NotFound`. Valores são inteiros de centavos.

## Dependência

`app_id`: `io.katua.sk.med.finance`. Faixa no manifesto do consumidor: a versão corrente da suíte, `>=0.1.0,<0.2.0` na primeira linha. Importe só o módulo `service_api` desta app.

<!-- BEGIN GENERATED: tools/service_reference.py -->

## Serviços

### `FinanceService`

#### `add_price_item(*, actor, code, description, amount, price_list_id=None, idempotency_key) -> PriceItemInfo`

Add an item to a price list (the default one when not informed).

- **Autorização:** alteração na tabela de preços.
- **Erros:** NotFound; Forbidden; InvalidInput com o nome do campo; Conflict("integrity_conflict") para código repetido na tabela.
- **Efeitos:** grava o item. A mesma chave devolve o já gravado.

#### `desks(*, actor) -> tuple[DeskInfo, ...]`

The cash desks the actor reads, the default first.

- **Autorização:** leitura de cada caixa.
- **Erros:** nenhum além do contrato.
- **Efeitos:** nenhum.

#### `price_for(*, actor, code, price_list_id=None) -> PriceItemInfo | None`

The active item of a code (the appointment type's billing code), or ``None``.

- **Autorização:** leitura da tabela de preços.
- **Erros:** NotFound para tabela ilegível ou sem tabela padrão.
- **Efeitos:** nenhum.

#### `price_items(*, actor, price_list_id=None, query='', active_only=True) -> tuple[PriceItemInfo, ...]`

Items of a price list (the default one when not informed), by code.

- **Autorização:** leitura da tabela de preços.
- **Erros:** NotFound para tabela ilegível ou sem tabela padrão; InvalidInput para busca longa demais.
- **Efeitos:** nenhum.

#### `price_lists(*, actor) -> tuple[PriceListInfo, ...]`

The price lists the actor reads, the default first.

- **Autorização:** leitura de cada tabela de preços.
- **Erros:** nenhum além do contrato.
- **Efeitos:** nenhum.

#### `setup(*, actor, desk_name='', price_list_name='', writer_group_ids=(), reader_group_ids=(), price_manager_group_ids=(), idempotency_key) -> DeskInfo`

Create the default price list and cash desk, and prepare the ledger book for them.

- **Autorização:** a capacidade ``access.manage``, ``create`` nas tabelas de preços e de caixas, e a gestão do livro contábil padrão (que é criado se não existir).
- **Erros:** Forbidden; InvalidInput para nome inválido ou mais de 20 grupos; Conflict("already_set_up") com um caixa padrão criado por outra chave; Unavailable com o livro contábil desativado.
- **Efeitos:** cria o livro padrão (se faltar), aplica o plano de serviços, cria as contas e vincula as chaves do financeiro; cria a tabela de preços e o caixa padrão (privados, do ator), dá ao papel ``member`` leitura e alteração das duas tabelas, concede leitura aos grupos de leitura, leitura e alteração do caixa aos de escrita e alteração da tabela de preços aos gestores de preço. A mesma chave devolve o já criado.

#### `update_price_item(*, actor, item_id, changes, expected_revision) -> PriceItemInfo`

Change the description, amount or activity of a price item, with CAS (the code never changes).

- **Autorização:** alteração na tabela de preços.
- **Erros:** NotFound; Forbidden; InvalidInput com o nome do campo; Conflict("stale_revision").
- **Efeitos:** grava só os campos que mudaram; contas já confirmadas não mudam.

## DTOs

### `DeskInfo`

| Campo | Tipo |
|---|---|
| `sysid` | `UUID` |
| `name` | `str` |
| `book_id` | `UUID` |
| `price_list_id` | `UUID | None` |
| `is_default` | `bool` |
| `revision` | `int` |
| `writable` | `bool` |

### `PriceItemInfo`

| Campo | Tipo |
|---|---|
| `sysid` | `UUID` |
| `price_list_id` | `UUID` |
| `code` | `str` |
| `description` | `str` |
| `amount` | `int` |
| `is_active` | `bool` |
| `revision` | `int` |

### `PriceListInfo`

| Campo | Tipo |
|---|---|
| `sysid` | `UUID` |
| `name` | `str` |
| `currency` | `str` |
| `is_default` | `bool` |
| `revision` | `int` |
| `writable` | `bool` |

<!-- END GENERATED -->

## Contribuições a outras apps

Registradas no `ready()`: o passo de configuração `med_finance.desk` de `med_patients` e as chaves de conta `med_finance.*` do livro contábil.

## Histórico de versões
| Versão | Mudança |
|---|---|
| 0.1.0 | Primeira versão |
