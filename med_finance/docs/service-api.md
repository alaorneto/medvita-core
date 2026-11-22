# API de serviços: Financeiro

Referência de `FinanceService` (`applications.med_finance.service_api`). O contrato geral está na [API de serviços do núcleo](https://github.com/alaorneto/skeleton/blob/v0.3.0/docs/service-api.md).

## Visão geral

`FinanceService` dá às outras apps e às superfícies desta app os preços, os caixas, as contas, os pagamentos e os recibos da organização atual, com a autorização do ator do contexto. Todos os métodos exigem a app ativa (`Unavailable`), contexto de organização e `actor` igual ao do contexto. Comandos rodam num savepoint da transação do chamador. Registro inexistente, de outra organização ou ilegível respondem o mesmo `NotFound`. Valores são inteiros de centavos.

## Dependência

`app_id`: `io.medvita.finance`. Faixa no manifesto do consumidor: a versão corrente da suíte, `>=0.1.0,<0.2.0` na primeira linha. Importe só o módulo `service_api` desta app.

<!-- BEGIN GENERATED: tools/service_reference.py -->

## Serviços

### `FinanceService`

#### `add_item(*, actor, charge_id, item, expected_revision) -> ChargeDetail`

Add a line to a draft charge, with CAS on the charge.

- **Autorização:** alteração no caixa.
- **Erros:** NotFound; Forbidden; InvalidInput; Conflict("not_draft") ou Conflict("stale_revision").
- **Efeitos:** grava o item e recalcula o total.

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

#### `cancel_charge(*, actor, charge_id, reason, expected_revision) -> ChargeDetail`

Cancel a charge without registered payments (reverse them first); its title is cancelled.

- **Autorização:** alteração no caixa.
- **Erros:** NotFound; Forbidden; InvalidInput sem motivo; Conflict("has_payments"), Conflict("cancelled"), Conflict("stale_revision") ou Conflict("ledger_rejected").
- **Efeitos:** grava a situação e o motivo, cancela o título no livro e publica ``charge_cancelled``.

#### `charge(*, actor, charge_id) -> ChargeDetail`

One charge with its items.

- **Autorização:** leitura do caixa.
- **Erros:** NotFound para conta inexistente, de outra organização ou ilegível.
- **Efeitos:** nenhum.

#### `charge_for_appointment(*, actor, appointment_id, confirm=True, idempotency_key) -> ChargeDetail`

The charge of a private appointment, created on first use from its billing code and the desk's price list.

- **Autorização:** leitura da consulta e do paciente; alteração no caixa padrão.
- **Erros:** NotFound; Forbidden; InvalidInput("not_private") para convênio ou cortesia, InvalidInput para consulta cancelada ou sem preço ativo para o código de cobrança.
- **Efeitos:** os de ``create_charge``.

#### `charges(*, actor, patient_id=None, status=None, desk_id=None, start=None, end=None, cursor=None, page_size=50) -> Page[ChargeInfo]`

Charges of the desks the actor reads, newest first, filtered by patient, status, desk or due date.

- **Autorização:** leitura de cada caixa.
- **Erros:** InvalidInput para situação, datas, cursor ou tamanho inválidos.
- **Efeitos:** nenhum.

#### `charges_for_origin(*, actor, origin_app, origin_key) -> tuple[ChargeInfo, ...]`

The charge another app created for one of its records (an appointment, for example).

- **Autorização:** leitura do caixa.
- **Erros:** nenhum além do contrato.
- **Efeitos:** nenhum.

#### `close_session(*, actor, session_id, counted_amount, expected_revision, note='') -> SessionInfo`

Close a session with the counted cash; the difference to the expected cash is recorded.

- **Autorização:** alteração no caixa, e ser quem abriu a sessão ou ter a gestão de acesso do caixa.
- **Erros:** NotFound; Forbidden; InvalidInput; Conflict("session_closed") ou Conflict("stale_revision").
- **Efeitos:** grava valor contado, esperado e diferença; a sessão fechada não recebe pagamento nem movimento.

#### `confirm_charge(*, actor, charge_id, expected_revision) -> ChargeDetail`

Confirm a draft charge: its items freeze and it becomes a receivable title in the ledger.

- **Autorização:** alteração no caixa (e, pelo livro, alteração na conta, que é a origem do título).
- **Erros:** NotFound; Forbidden; InvalidInput para total zero; Conflict("not_draft"), Conflict("stale_revision") ou Conflict("ledger_rejected").
- **Efeitos:** cria o título, grava a situação "em aberto" e publica ``charge_confirmed``.

#### `create_charge(*, actor, patient_id, items, desk_id=None, due_date=None, payer_name='', payer_document='', appointment_id=None, origin_app='', origin_key='', confirm=True, note='', idempotency_key) -> ChargeDetail`

Create a charge of the patient at a desk; confirmed (the default), it becomes a receivable title.

- **Autorização:** alteração no caixa e leitura do paciente (e da consulta, quando informada).
- **Erros:** NotFound; Forbidden; InvalidInput para itens, valores, pagador, origem não registrada, consulta de outro paciente ou total zero ao confirmar; Conflict("ledger_rejected").
- **Efeitos:** grava a conta e os itens; ao confirmar, cria o título no livro (sem nome nem documento do paciente, só ``party_ref``) e publica ``charge_confirmed``. A mesma chave devolve a já criada.

#### `current_session(*, actor, desk_id=None) -> SessionInfo | None`

The open session of a cash desk (the default one when not informed), or ``None``.

- **Autorização:** leitura do caixa.
- **Erros:** NotFound para caixa ilegível ou sem caixa padrão.
- **Efeitos:** nenhum.

#### `daily_summary(*, actor, date, desk_id=None) -> DailySummary`

One local day of the desks the actor reads: received by method, reversals, charges created and open.

- **Autorização:** leitura de cada caixa.
- **Erros:** InvalidInput para data inválida; NotFound para caixa ilegível.
- **Efeitos:** nenhum.

#### `desks(*, actor) -> tuple[DeskInfo, ...]`

The cash desks the actor reads, the default first.

- **Autorização:** leitura de cada caixa.
- **Erros:** nenhum além do contrato.
- **Efeitos:** nenhum.

#### `issue_receipt(*, actor, payment_id, idempotency_key) -> ReceiptInfo`

Issue the receipt of a payment (one per payment), numbered per year without gaps and sealed.

- **Autorização:** alteração no caixa da conta.
- **Erros:** NotFound; Forbidden; Conflict("reversed") para pagamento estornado.
- **Efeitos:** grava o recibo, pede o número depois de validar tudo, sela e publica ``receipt_issued`` (sem nome nem documento). Repetir devolve o mesmo recibo.

#### `open_session(*, actor, desk_id=None, opening_amount=0, idempotency_key) -> SessionInfo`

Open a session of the cash desk with the cash in the drawer.

- **Autorização:** alteração no caixa.
- **Erros:** NotFound; Forbidden; InvalidInput para valor inválido; Conflict("session_already_open").
- **Efeitos:** grava a sessão aberta. A mesma chave devolve a já aberta.

#### `patient_balance(*, actor, patient_id) -> int`

What the patient still owes in the open and partially paid charges the actor reads (centavos).

- **Autorização:** leitura de cada caixa.
- **Erros:** InvalidInput para identificador inválido.
- **Efeitos:** nenhum.

#### `payments(*, actor, charge_id) -> tuple[PaymentInfo, ...]`

The payments of a charge, oldest first.

- **Autorização:** leitura do caixa.
- **Erros:** NotFound para conta ilegível.
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

#### `receipt(*, actor, receipt_id) -> ReceiptInfo`

One receipt, marked when voided.

- **Autorização:** leitura do caixa.
- **Erros:** NotFound para recibo inexistente, de outra organização ou ilegível.
- **Efeitos:** nenhum.

#### `receipts(*, actor, charge_id=None, year=None, cursor=None, page_size=50) -> Page[ReceiptInfo]`

Receipts of the desks the actor reads, newest first, by charge or year.

- **Autorização:** leitura de cada caixa.
- **Erros:** InvalidInput para ano, cursor ou tamanho inválidos.
- **Efeitos:** nenhum.

#### `receivables(*, actor, as_of=None) -> ReceivablesReport`

Open balances of the charges by days overdue: to come, 1–30, 31–60, 61–90 and over 90.

- **Autorização:** leitura de cada caixa.
- **Erros:** InvalidInput para data inválida.
- **Efeitos:** nenhum.

#### `register_payment(*, actor, charge_id, method, amount, expected_revision, idempotency_key, installments=1, authorization_code='', issue_receipt=True) -> PaymentInfo`

Receive a payment of a charge in the open session of its desk and settle the title in the ledger.

- **Autorização:** alteração no caixa da conta.
- **Erros:** NotFound; Forbidden; InvalidInput para forma, valor acima do saldo, parcelas (mais de uma só no crédito) ou código de autorização inválidos; Conflict("not_open") para conta em rascunho, paga ou cancelada; Conflict("no_open_session"); Conflict("stale_revision") com a revisão da conta; Conflict("ledger_rejected").
- **Efeitos:** grava o pagamento, a baixa no livro, o total pago e a situação da conta; publica ``payment_registered`` e, ao quitar, ``charge_paid``; com ``issue_receipt``, emite o recibo na mesma transação. A mesma chave devolve o já registrado.

#### `remove_item(*, actor, charge_id, item_id, expected_revision) -> ChargeDetail`

Remove a line of a draft charge, with CAS on the charge.

- **Autorização:** alteração no caixa.
- **Erros:** NotFound; Forbidden; Conflict("not_draft") ou Conflict("stale_revision").
- **Efeitos:** exclusão lógica do item e novo total.

#### `reverse_payment(*, actor, payment_id, reason, expected_revision) -> PaymentInfo`

Reverse a payment: the settlement is reversed in the ledger and the charge is open again.

- **Autorização:** alteração no caixa da conta.
- **Erros:** NotFound; Forbidden; InvalidInput sem motivo; Conflict("reversed"), Conflict("receipt_not_voided") com recibo vivo, Conflict("stale_revision") com a revisão do pagamento, Conflict("ledger_rejected").
- **Efeitos:** grava o estorno, estorna a baixa, recalcula a conta e publica ``payment_reversed``. Um estorno de sessão já fechada não muda o esperado gravado no fechamento.

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

#### `verify_receipt(*, actor, receipt_id) -> bool`

Whether the stored content of the receipt still matches its seal.

- **Autorização:** leitura do caixa.
- **Erros:** NotFound para recibo ilegível.
- **Efeitos:** nenhum.

#### `void_receipt(*, actor, receipt_id, reason, idempotency_key) -> ReceiptInfo`

Void a receipt: it stays intact, marked as voided; the number is never reused.

- **Autorização:** alteração no caixa.
- **Erros:** NotFound; Forbidden; InvalidInput sem motivo.
- **Efeitos:** grava a anulação e publica ``receipt_voided``. Repetir devolve o mesmo recibo anulado.

## DTOs

### `AgingRow`

| Campo | Tipo |
|---|---|
| `name` | `str` |
| `amount` | `int` |
| `count` | `int` |

### `ChargeDetail`

| Campo | Tipo |
|---|---|
| `charge` | `ChargeInfo` |
| `items` | `tuple[ChargeItemInfo, ...]` |
| `writable` | `bool` |

### `ChargeInfo`

| Campo | Tipo |
|---|---|
| `sysid` | `UUID` |
| `desk_id` | `UUID` |
| `code` | `str` |
| `patient_id` | `UUID` |
| `payer_name` | `str` |
| `payer_document` | `str` |
| `status` | `str` |
| `total` | `int` |
| `paid_total` | `int` |
| `balance` | `int` |
| `due_date` | `date` |
| `origin_app` | `str` |
| `origin_key` | `str` |
| `appointment_id` | `UUID | None` |
| `ledger_title_id` | `UUID | None` |
| `note` | `str` |
| `confirmed_at` | `datetime | None` |
| `cancelled_at` | `datetime | None` |
| `cancel_reason` | `str` |
| `revision` | `int` |

### `ChargeItemInfo`

| Campo | Tipo |
|---|---|
| `sysid` | `UUID` |
| `code` | `str` |
| `description` | `str` |
| `quantity` | `int` |
| `unit_amount` | `int` |
| `discount_amount` | `int` |
| `total` | `int` |

### `ChargeItemInput`

A line to bill: with ``code`` and no ``unit_amount``, the price comes from the desk's price list.

| Campo | Tipo |
|---|---|
| `code` | `str` |
| `description` | `str` |
| `quantity` | `int` |
| `unit_amount` | `int | None` |
| `discount_amount` | `int` |

### `ChargeOrigin`

| Campo | Tipo |
|---|---|
| `app_label` | `str` |
| `label` | `Any` |

### `DailySummary`

| Campo | Tipo |
|---|---|
| `date` | `date` |
| `by_method` | `tuple[MethodTotal, ...]` |
| `received` | `int` |
| `reversed` | `int` |
| `charges_created` | `int` |
| `charged` | `int` |
| `open_due` | `int` |

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

### `PaymentInfo`

| Campo | Tipo |
|---|---|
| `sysid` | `UUID` |
| `charge_id` | `UUID` |
| `session_id` | `UUID` |
| `method` | `str` |
| `amount` | `int` |
| `received_at` | `datetime` |
| `installments` | `int` |
| `authorization_code` | `str` |
| `received_by_id` | `UUID` |
| `status` | `str` |
| `reversed_at` | `datetime | None` |
| `reverse_reason` | `str` |
| `ledger_settlement_id` | `UUID | None` |
| `revision` | `int` |

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

### `ReceiptInfo`

| Campo | Tipo |
|---|---|
| `sysid` | `UUID` |
| `charge_id` | `UUID` |
| `payment_id` | `UUID` |
| `number` | `str` |
| `issued_at` | `datetime` |
| `amount` | `int` |
| `method` | `str` |
| `payer_name` | `str` |
| `payer_document` | `str` |
| `patient_name` | `str` |
| `description` | `str` |
| `issuer_name` | `str` |
| `issuer_document` | `str` |
| `professional_name` | `str` |
| `professional_council` | `str` |
| `professional_tax_id` | `str` |
| `seal_digest` | `str` |
| `voided` | `bool` |
| `void_reason` | `str` |
| `voided_at` | `datetime | None` |
| `revision` | `int` |

### `ReceivablesReport`

| Campo | Tipo |
|---|---|
| `as_of` | `date` |
| `buckets` | `tuple[AgingRow, ...]` |
| `total` | `int` |

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

## Eventos publicados

| Tipo | Quando | Payload |
|---|---|---|
| `med_finance.charge_confirmed`, `_paid`, `_cancelled` | confirmação, quitação e cancelamento da conta | `code`, `desk`, `patient`, `status`, `total`, `origin_app`, `origin_key` |
| `med_finance.payment_registered`, `_reversed` | `register_payment`, `reverse_payment` | `charge`, `method`, `amount`, `status` |
| `med_finance.receipt_issued`, `_voided` | emissão e anulação do recibo | `number`, `charge`, `amount`, `seal_digest` |

Nunca nome nem documento do paciente ou do pagador.

## Pontos de extensão

`register_charge_origin(ChargeOrigin(app_label, label))`, reexportada por este módulo e chamada no `ready()`: declara uma app que cria contas por `create_charge(origin_app=..., origin_key=...)`; a mesma origem devolve a mesma conta. O financeiro registra a origem `med_scheduling` (a consulta).

## Contribuições a outras apps

Registradas no `ready()`: o passo de configuração `med_finance.desk`, a aba `med_finance.account` (com `visible`), a linha do tempo e o relatório do titular `med_finance.finance` e a guarda `med_finance.retention` de `med_patients`; a ação `med_finance.collect` das consultas de `med_scheduling`; as chaves de conta `med_finance.*` e as regras `med_finance.cash_supply` e `cash_withdrawal` do livro.

## API REST

As rotas de `/api/v1/o/<org>/apps/med_finance/` estão em `docs/spec.md` (seção "API REST").

## Histórico de versões
| Versão | Mudança |
|---|---|
| 0.1.0 | Primeira versão |
