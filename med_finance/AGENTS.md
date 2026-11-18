# med_finance: Financeiro

Regras do núcleo: `AGENTS.md` do Skeleton (link no [`AGENTS.md` da raiz](../AGENTS.md)). Regras da suíte: [`../AGENTS.md`](../AGENTS.md). Este arquivo só traz o que é próprio desta app.

## Propósito e limites

Frente de caixa do consultório: tabela de preços, caixa com abertura e fechamento, conta do paciente, recebimento particular e recibos numerados. Títulos, baixas, lançamentos e relatórios contábeis ficam no `skeleton_ledger`.

**Não faz:** TISS, NFS-e, repasse, maquininha integrada, cobrança recorrente.

## Tabelas

- Contêineres `PriceList` (tabela de preços) e `CashDesk` (um caixa).
- Derivadas: `PriceItem` (da tabela); `CashSession`, `Charge` (do caixa); `CashMovement` (da sessão); `ChargeItem`, `Payment`, `Receipt` (da conta); `ReceiptVoid` (do recibo).
- Selada: `Receipt`.
- Pagador, documento e nomes fotografados no recibo são `personal_fields`.

## Serviços e pontos de extensão

- Oferece `FinanceService` e o registry `register_charge_origin`.
- Publica `charge_confirmed`, `charge_paid`, `charge_cancelled`, `payment_registered`, `payment_reversed`, `receipt_issued` e `receipt_voided`.
- Consome `PatientService`, `SchedulingService` e o `LedgerService` do núcleo. Não consome os eventos da agenda: um consumidor roda em contexto de sistema, onde o núcleo não numera nem lê o título (alaorneto/skeleton#577); a conta da consulta nasce por "Receber" (`charge_for_appointment`).
- `ledger_bridge.py` é o único módulo que chama o livro. O livro autoriza título, baixa e lançamento de regra pelo registro de origem desta app; o caixa guarda as contas do livro de cada forma de pagamento (`payment_accounts`), resolvidas no `setup`.
- Contribui em `integration.py`: origem de conta `med_scheduling`, ação "Receber", aba "Financeiro" (só para quem lê um caixa), linha do tempo, relatório do titular e a guarda de retenção de 5 anos.
- Superfícies: páginas em `views.py` e API REST em `api.py`; nenhuma consulta modelo.
- As referências do recibo (conta e pagamento) ficam fora de `seal_fields`, porque já são imutáveis; o resumo as cobre pelo `extra` (`receipt_extra`).

## Invariantes do domínio

1. Dinheiro é inteiro em centavos; nunca `float`.
2. Número de recibo não tem lacuna nem é reutilizado; recibo emitido não muda (anulação é outro registro).
3. Todo recebimento pertence a uma sessão de caixa aberta.
4. Todo valor confirmado tem título no livro e todo pagamento tem baixa; estorno é lançamento novo.
5. Nome e documento do paciente não vão para o livro: o título leva só o `sysid`.

## Testes e especificação

- Testes: `python -m pytest med_finance/tests -q -n auto` a partir da raiz, com o ambiente de `docs/development.md`.
- Especificação: `docs/spec.md`, decisões em `docs/adr.md` e contrato do serviço em `docs/service-api.md`, todos neste pacote.
