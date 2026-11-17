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

### Preços

`price_items` lista os itens (da tabela padrão, sem `price_list_id`); `price_for(code)` devolve o item ativo do código ou `None`. `add_price_item` exige alteração na tabela; código repetido é `Conflict`. `update_price_item` muda descrição, valor ou atividade, com CAS; o código nunca muda.

## Acceptance

- O `setup` prepara o livro com as chaves do financeiro vinculadas, é idempotente pela chave e só o administrador o faz; com o livro desativado, nada é criado.
- A recepção consulta preços e não os altera; a organização B não vê os preços da A.
- Valor negativo, fracionário ou em texto é recusado.
