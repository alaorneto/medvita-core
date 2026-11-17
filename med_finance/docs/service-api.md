# API de serviços: Financeiro

Referência de `FinanceService` (`applications.med_finance.service_api`). O contrato geral está na [API de serviços do núcleo](https://github.com/alaorneto/skeleton/blob/f38c9a02166d63e402d2c7708e616ae842441665/docs/service-api.md).

## Visão geral

`FinanceService` dá às outras apps e às superfícies desta app os preços, os caixas, as contas, os pagamentos e os recibos da organização atual, com a autorização do ator do contexto. Todos os métodos exigem a app ativa (`Unavailable`), contexto de organização e `actor` igual ao do contexto. Comandos rodam num savepoint da transação do chamador. Registro inexistente, de outra organização ou ilegível respondem o mesmo `NotFound`. Valores são inteiros de centavos.

## Dependência

`app_id`: `io.katua.sk.med.finance`. Faixa no manifesto do consumidor: a versão corrente da suíte, `>=0.1.0,<0.2.0` na primeira linha. Importe só o módulo `service_api` desta app.

<!-- BEGIN GENERATED: tools/service_reference.py -->

## Serviços

### `FinanceService`

#### `add_movement(*, actor, session_id, kind, amount, reason, idempotency_key) -> MovementInfo`

Record a supply or a withdrawal of cash in an open session and post it to the ledger.

- **Autorização:** alteração no caixa.
- **Erros:** NotFound; Forbidden; InvalidInput para tipo, valor ou motivo inválidos; Conflict("session_closed"); Conflict("insufficient_cash") para sangria maior que o dinheiro esperado; Conflict("ledger_rejected") quando o livro recusa (período travado, chave sem conta).
- **Efeitos:** grava o movimento e o lançamento no livro (regra ``med_finance.cash_supply`` ou ``cash_withdrawal``). A mesma chave devolve o já gravado.

#### `add_price_item(*, actor, code, description, amount, price_list_id=None, idempotency_key) -> PriceItemInfo`

Add an item to a price list (the default one when not informed).

- **Autorização:** alteração na tabela de preços.
- **Erros:** NotFound; Forbidden; InvalidInput com o nome do campo; Conflict("integrity_conflict") para código repetido na tabela.
- **Efeitos:** grava o item. A mesma chave devolve o já gravado.

#### `close_session(*, actor, session_id, counted_amount, expected_revision, note='') -> SessionInfo`

Close a session with the counted cash; the difference to the expected cash is recorded.

- **Autorização:** alteração no caixa, e ser quem abriu a sessão ou ter a gestão de acesso do caixa.
- **Erros:** NotFound; Forbidden; InvalidInput; Conflict("session_closed") ou Conflict("stale_revision").
- **Efeitos:** grava valor contado, esperado e diferença; a sessão fechada não recebe pagamento nem movimento.

#### `current_session(*, actor, desk_id=None) -> SessionInfo | None`

The open session of a cash desk (the default one when not informed), or ``None``.

- **Autorização:** leitura do caixa.
- **Erros:** NotFound para caixa ilegível ou sem caixa padrão.
- **Efeitos:** nenhum.

#### `desks(*, actor) -> tuple[DeskInfo, ...]`

The cash desks the actor reads, the default first.

- **Autorização:** leitura de cada caixa.
- **Erros:** nenhum além do contrato.
- **Efeitos:** nenhum.

#### `open_session(*, actor, desk_id=None, opening_amount=0, idempotency_key) -> SessionInfo`

Open a session of the cash desk with the cash in the drawer.

- **Autorização:** alteração no caixa.
- **Erros:** NotFound; Forbidden; InvalidInput para valor inválido; Conflict("session_already_open").
- **Efeitos:** grava a sessão aberta. A mesma chave devolve a já aberta.

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

#### `session_report(*, actor, session_id) -> SessionReport`

Totals of a session: by payment method, supplies, withdrawals and the expected cash.

- **Autorização:** leitura do caixa.
- **Erros:** NotFound para sessão ilegível.
- **Efeitos:** nenhum.

#### `sessions(*, actor, desk_id=None, start=None, end=None, cursor=None, page_size=50) -> Page[SessionInfo]`

Sessions of a cash desk, newest first.

- **Autorização:** leitura do caixa.
- **Erros:** NotFound; InvalidInput para datas sem fuso, cursor ou tamanho inválidos.
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

### `MethodTotal`

| Campo | Tipo |
|---|---|
| `method` | `str` |
| `amount` | `int` |
| `count` | `int` |

### `MovementInfo`

| Campo | Tipo |
|---|---|
| `sysid` | `UUID` |
| `session_id` | `UUID` |
| `kind` | `str` |
| `amount` | `int` |
| `reason` | `str` |
| `at` | `datetime` |
| `ledger_entry_id` | `UUID | None` |

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

### `SessionInfo`

| Campo | Tipo |
|---|---|
| `sysid` | `UUID` |
| `desk_id` | `UUID` |
| `opened_by_id` | `UUID` |
| `opened_at` | `datetime` |
| `opening_amount` | `int` |
| `status` | `str` |
| `closed_by_id` | `UUID | None` |
| `closed_at` | `datetime | None` |
| `counted_amount` | `int | None` |
| `expected_amount` | `int | None` |
| `difference` | `int | None` |
| `note` | `str` |
| `revision` | `int` |

### `SessionReport`

| Campo | Tipo |
|---|---|
| `session` | `SessionInfo` |
| `by_method` | `tuple[MethodTotal, ...]` |
| `supplies` | `int` |
| `withdrawals` | `int` |
| `expected_cash` | `int` |
| `movements` | `tuple[MovementInfo, ...]` |

<!-- END GENERATED -->

## Contribuições a outras apps

Registradas no `ready()`: o passo de configuração `med_finance.desk` de `med_patients` e as chaves de conta `med_finance.*` do livro contábil.

## Histórico de versões
| Versão | Mudança |
|---|---|
| 0.1.0 | Primeira versão |
