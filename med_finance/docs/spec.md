# Financeiro

A frente de caixa do consultório: tabela de preços, conta do paciente, recebimento particular (dinheiro, Pix, cartão, transferência), caixa com abertura e fechamento e recibos numerados. A contabilidade (títulos, baixas, lançamentos, relatórios, contas a pagar) fica no livro contábil do núcleo (`skeleton_ledger`). A app **não** faz TISS, NFS-e, repasse, maquininha integrada nem cobrança recorrente.

## Contract

### Ativação e dependências

Depende de `io.katua.sk.med.patients` (o paciente de cada conta), de `io.katua.sk.med.scheduling` (a consulta e o emitente do recibo) e de `org.skeleton.ledger` (títulos, baixas e lançamentos). Instalada globalmente e ativada por organização, depois das dependências.

### Acesso

Dois contêineres (`SecuredRecord` expostos):

- `PriceList`: uma tabela de preços; os itens derivam dela.
- `CashDesk`: um caixa, ligado a um livro contábil; sessões, movimentos, contas, pagamentos e recibos derivam dele.

O `setup` (capacidade `access.manage` e gestão do livro padrão) prepara o livro (cria o padrão se faltar, aplica o plano de serviços, cria as contas de Pix, cartões e aportes, vincula as chaves `med_finance.*`), cria a tabela de preços e o caixa padrão, privados e do administrador, dá ao papel `member` leitura e alteração das duas tabelas e concede: leitura do caixa e da tabela aos grupos de leitura, leitura e alteração do caixa aos de escrita, alteração da tabela de preços aos gestores de preço.

O livro autoriza títulos, baixas e lançamentos de regra pelo registro de origem (a conta, o movimento): quem trabalha no caixa não precisa de acesso ao livro. O caixa guarda as contas do livro de cada forma de pagamento (`payment_accounts`), resolvidas no `setup` por quem gere o livro.

### Modelo de dados

Valores sempre em inteiros de centavos.

**`PriceList`** (contêiner): `name`, `currency` (`BRL`, imutável), `is_default`.

**`PriceItem`** (derivada da tabela de preços): `code` (único por tabela entre os vivos; é o `billing_code` dos tipos de atendimento), `description`, `amount`, `is_active`.

**`CashDesk`** (contêiner): `name`, `book` (o livro, imutável), `price_list` (a tabela padrão do caixa), `payment_accounts`, `is_default`.

**`CashSession`** (derivada do caixa): `opened_by`, `opened_at`, `opening_amount` (imutáveis), `status` (aberto, fechado; uma sessão aberta por caixa), `closed_by`, `closed_at`, `counted_amount`, `expected_amount`, `difference`, `note`.

**`CashMovement`** (derivada da sessão, imutável): `kind` (suprimento ou sangria), `amount`, `reason`, `at`, `ledger_entry` (o lançamento no livro).

**`Charge`** (derivada do caixa): `code` (`C` + 8 dígitos da sequência `med_finance.charge`), `patient`, `payer_name` e `payer_document` (`personal_fields`; vazio = o próprio paciente; CPF ou CNPJ válido), `status` (rascunho, em aberto, parcialmente paga, paga, cancelada), `total`, `paid_total`, `due_date`, `origin_app` e `origin_key` (uma conta por origem), `appointment`, `ledger_title` (o título no livro), `note`, `confirmed_at`, `cancelled_at`, `cancel_reason`.

**`ChargeItem`** (derivada da conta): `price_item`, `code`, `description`, `quantity`, `unit_amount`, `discount_amount` (até o valor do item), `total`. Muda só com a conta em rascunho.

**`Payment`** (derivada da conta): `session` (a sessão aberta do caixa da conta), `method` (dinheiro, Pix, débito, crédito, transferência, outro), `amount`, `received_at`, `installments` (mais de uma só no crédito), `authorization_code`, `received_by` (imutáveis), `status` (registrado, estornado), `reversed_at`, `reverse_reason`, `ledger_settlement` (a baixa no livro).

### Preços

`price_items` lista os itens (da tabela padrão, sem `price_list_id`); `price_for(code)` devolve o item ativo do código ou `None`. `add_price_item` exige alteração na tabela; código repetido é `Conflict`. `update_price_item` muda descrição, valor ou atividade, com CAS; o código nunca muda.

### Caixa

- `open_session` abre uma sessão do caixa (alteração no caixa); outra aberta é `Conflict("session_already_open")`, também na corrida (restrição única).
- `add_movement` grava suprimento ou sangria e lança no livro pela regra `med_finance.cash_supply` (débito em dinheiro, crédito em aportes e retiradas) ou `cash_withdrawal` (o inverso), autorizada pelo próprio movimento; sangria maior que o dinheiro esperado é `Conflict("insufficient_cash")`; sessão fechada não recebe movimento.
- Dinheiro esperado = abertura + pagamentos em dinheiro não estornados + suprimentos − sangrias. `close_session` grava contado, esperado e diferença; a diferença não impede fechar. Fecha quem abriu ou quem gere o acesso do caixa.
- `session_report` soma por forma de pagamento, suprimentos, sangrias e o esperado.
- O livro recusando (período travado, chave sem conta) vira `Conflict("ledger_rejected")` e nada fica pela metade.

### Contas

- `create_charge` (alteração no caixa e leitura do paciente) grava a conta com os itens; um item com `code` e sem valor usa o preço ativo da tabela do caixa. Com `confirm=True` (padrão) a conta é confirmada na hora.
- Confirmar congela os itens, cria o título a receber no livro (categoria `med_finance.service_revenue`, origem a própria conta, contraparte só por `party_ref` = o `sysid` do paciente, nunca nome nem documento) e publica `charge_confirmed`. Total zero não confirma: cortesia é da agenda (`payment_kind="courtesy"`), não uma conta zerada.
- `origin_app` (uma origem registrada por `register_charge_origin`) e `origin_key` fazem a mesma origem devolver a mesma conta.
- `cancel_charge` exige motivo e nenhum pagamento ativo (estorne antes); cancela o título e publica `charge_cancelled`.
- `patient_balance` soma o que o paciente deve nas contas em aberto que o ator lê.
- Eventos `charge_confirmed`, `charge_paid`, `charge_cancelled`: `code`, `desk`, `patient`, `status`, `total`, `origin_app`, `origin_key`.

### Pagamentos

- `register_payment` usa a revisão da **conta** como CAS (dois recebimentos simultâneos: um vence), exige conta em aberto, valor até o saldo (troco é do operador) e a sessão aberta do caixa da conta (`Conflict("no_open_session")`). Baixa o título no livro na conta do caixa daquela forma de pagamento (dinheiro, Pix a compensar, cartões a receber, banco), atualiza o total pago e a situação, publica `payment_registered` e, ao quitar, `charge_paid`; com `issue_receipt`, emite o recibo na mesma transação.
- `reverse_payment` exige motivo e o recibo anulado, estorna a baixa no livro (que volta o saldo do título), reabre a conta (parcialmente paga ou em aberto) e publica `payment_reversed`. O estorno de uma sessão já fechada não muda o esperado gravado no fechamento.
- Eventos `payment_registered` e `payment_reversed`: `charge`, `method`, `amount`, `status`.

## Acceptance

- O `setup` prepara o livro com as chaves do financeiro vinculadas, é idempotente pela chave e só o administrador o faz; com o livro desativado, nada é criado.
- A recepção consulta preços e não os altera; a organização B não vê os preços da A.
- Valor negativo, fracionário ou em texto é recusado.
- Abrir, suprir, sangrar e fechar conferem o esperado e a diferença; cada movimento tem um lançamento no livro.
- O título da conta confirmada não leva nome nem documento do pagador; a mesma origem devolve a mesma conta.
- Pagamento parcial e depois o restante quitam a conta e o título; o estorno reabre os dois.
