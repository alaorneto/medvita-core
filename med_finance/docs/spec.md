# Financeiro

A frente de caixa do consultório: tabela de preços, conta do paciente, recebimento particular (dinheiro, Pix, cartão, transferência), caixa com abertura e fechamento e recibos numerados. A contabilidade (títulos, baixas, lançamentos, relatórios, contas a pagar) fica no livro contábil do núcleo (`skeleton_ledger`). A app **não** faz TISS, NFS-e, repasse, maquininha integrada nem cobrança recorrente.

## Contract

### Ativação e dependências

Depende de `io.medvita.patients` (o paciente de cada conta), de `io.medvita.scheduling` (a consulta e o emitente do recibo) e de `org.skeleton.ledger` (títulos, baixas e lançamentos). Instalada globalmente e ativada por organização, depois das dependências.

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

**`Receipt`** (derivada da conta, selável, um por pagamento): `number` (`<ano>/<6 dígitos>`, sequência `med_finance.receipt` sem lacunas, reiniciada a cada ano), `issued_at`, `amount`, `method`, e as fotografias da emissão: `payer_name` e `payer_document`, `patient_name`, `description` (itens da conta), `issuer_name` e `issuer_document` (o consultório), `professional_name`, `professional_council` e `professional_tax_id` (o profissional da consulta). Os campos pessoais estão em `personal_fields`.

**`ReceiptVoid`** (derivada do recibo, imutável, uma por recibo): `reason`, `voided_at`, `voided_by`.

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

### Recibos

- `register_payment(issue_receipt=True)` ou `issue_receipt` emitem o recibo do pagamento (um só; repetir devolve o mesmo): o número é pedido depois de todas as validações, na mesma transação do selo, e um rollback o devolve; o recibo é selado na emissão (`seal_record`, referências no `extra`) e publica `receipt_issued` (sem nome nem documento).
- `void_receipt` grava a anulação; o recibo continua íntegro (`verify_receipt` válido), aparece como anulado e o número não volta. O pagamento só é estornado com o recibo anulado.
- O recibo não substitui documento fiscal (NFS-e, Receita Saúde).

### Agenda e página do paciente

- "Receber" (`med_finance.collect`) aparece nas consultas em "chegou", "em atendimento" e "concluída". `charge_for_appointment` cria (ou devolve) a conta da consulta particular com o código de cobrança do tipo de atendimento e o preço da tabela do caixa padrão, origem `med_scheduling`; convênio, cortesia, consulta cancelada ou falta não geram conta.
- **Sem conta automática por evento.** A conta não nasce sozinha na chegada ou na conclusão: o consumidor de eventos do núcleo roda em contexto de sistema, sem ator, e nesse contexto não há como numerar a conta (`SequenceService`) nem ler o título do livro. A recepção usa "Receber"; a lacuna está registrada no núcleo.
- Aba "Financeiro" (`med_finance.account`, ordem 40), visível só para quem lê algum caixa; linha do tempo "Conta emitida" e "Pagamento recebido", sem valores; relatório do titular com contas (código, vencimento, total, situação) e recibos (número, valor).
- Guarda de retenção `med_finance.retention`: veta excluir ou anonimizar o paciente com conta dos últimos 5 anos (guarda fiscal; confirme o prazo com o contador).

### Relatórios

- `daily_summary(date)`: num dia local, o recebido por forma de pagamento, os estornos, as contas emitidas (quantidade e total) e as contas do dia em aberto; os totais em dinheiro batem com o saldo da conta de dinheiro no livro.
- `receivables(as_of)`: saldos em aberto por faixa de atraso (a vencer, 1–30, 31–60, 61–90, acima de 90 dias), calculados das contas desta app; o relatório de vencimentos do livro (`aging`) é o da contabilidade.
- As duas consultas são agregadas no banco: o número de consultas não cresce com o de contas.

### Páginas

Em `/o/<org>/apps/med_finance/` (nomes `med_finance:<nome>`); toda leitura e escrita passa pelo `FinanceService`. Valores são digitados em reais com vírgula ("250,00"), convertidos para centavos por `skeleton.common.money.parse` (nunca `float`), e mostrados com o filtro `brl`.

| Nome | Página |
|---|---|
| `desk` | Caixa do dia: abrir, totais por forma de pagamento, suprimento e sangria, fechar, contas recentes |
| `session` | Relatório da sessão (imprimível): abertura, formas de pagamento, movimentos, contado e diferença |
| `charges`, `charge_new`, `charge` | Contas com filtro de situação; nova conta (busca de paciente, item da tabela ou descrição livre, pagador); a conta com itens, pagamentos, recibos, receber, estornar, confirmar e cancelar |
| `collect` | Entrada pela consulta ("Receber"): a conta da consulta |
| `receipt`, `receipt_print` | Recibo com o valor por extenso, o resumo do selo, o aviso fiscal e "ANULADO" quando for o caso; anular |
| `prices` | Tabela de preços: itens, incluir, desativar |
| `daily`, `receivables` | Resumo do dia e contas a receber por atraso |
| `patient_section` | Aba "Financeiro" do paciente: contas e saldo |
| `setup` | Configuração inicial (administradores) |

### API REST

Em `/api/v1/o/<org>/apps/med_finance/`, valores em centavos:

| Método e caminho | O que faz | Token |
|---|---|---|
| `GET price-items/?q=` | Itens ativos da tabela padrão | `finance:read` |
| `GET charges/?patient=&status=&cursor=&page_size=` | Contas (`ChargeInfo`) | `finance:read` |
| `POST charges/` | Cria (e confirma, salvo `confirm: false`) uma conta; exige `Idempotency-Key`; campos `patient`, `items` (`code`, `description`, `quantity`, `unit_amount`, `discount_amount`), `payer_name`, `payer_document`, `note` | `finance:write` |
| `GET charges/<id>/` | A conta com os itens, com `ETag` | `finance:read` |
| `GET charges/<id>/payments/`, `POST charges/<id>/payments/` | Pagamentos; receber exige `Idempotency-Key` e `If-Match` com a revisão da conta (`method`, `amount`, `installments`, `authorization_code`) | `finance:read`; `finance:write` |
| `GET receipts/<id>/` | O recibo | `finance:read` |

Toda rota aceita a sessão do navegador e o token de um cliente fora dele (o access token OIDC de um cliente nativo, como o Medvita Desktop, ou um token `skt_`) nos métodos da coluna "Token", com as mesmas respostas, filtros, `ETag`, `If-Match` e `Idempotency-Key` da sessão. O escopo só restringe: o serviço autoriza o papel da pessoa como para a sessão, e um token com o escopo continua sem ver o que o papel não alcança. O token amplo (`openid profile email`) leva todos os escopos; um cliente que o operador limitou (`native_client register --scope`) precisa do escopo da coluna e do escopo de tabela do contêiner que o serviço autoriza (`med_finance.pricelist:read` e `med_finance.cashdesk:read`, e as ações de escrita do caixa para cobrar e receber). Sem o escopo, a resposta é 403 `permission_denied` ("O token não tem o escopo exigido."); método fora da coluna é 403 `token_not_allowed`. Cada operação aparece no `/api/v1/openapi.json` só para quem pode chamá-la.

Campo fora da lista é 400; conta ou recibo sem acesso ou de outra organização é 404.

## Acceptance

- O `setup` prepara o livro com as chaves do financeiro vinculadas, é idempotente pela chave e só o administrador o faz; com o livro desativado, nada é criado.
- A recepção consulta preços e não os altera; a organização B não vê os preços da A.
- Valor negativo, fracionário ou em texto é recusado.
- Abrir, suprir, sangrar e fechar conferem o esperado e a diferença; cada movimento tem um lançamento no livro.
- O título da conta confirmada não leva nome nem documento do pagador; a mesma origem devolve a mesma conta.
- Pagamento parcial e depois o restante quitam a conta e o título; o estorno reabre os dois.
- Recibos emitidos têm números consecutivos no ano; a anulação mantém o recibo e o número.
- A mesma consulta particular gera uma conta só; convênio não gera conta; a conta recente veta anonimizar o paciente.
- Pelas páginas, a recepção abre o caixa, cria a conta, recebe em dois meios, imprime o recibo, faz sangria e fecha o caixa com diferença.
