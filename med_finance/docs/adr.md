# Financeiro: decisões

## Context

O consultório recebe no balcão (dinheiro, Pix, cartão) e precisa de recibo e de fechamento de caixa; a contabilidade (títulos, baixas, relatórios) já existe no livro contábil do núcleo. Quem recebe não deve precisar gerir o livro.

## Decision

- **ADR-001, frente de caixa sobre o livro.** A app guarda o que é do balcão (preços, contas, pagamentos, sessões, recibos) e lança no livro: a conta confirmada vira título a receber, o pagamento vira baixa, suprimento e sangria viram lançamentos de regra. O livro é a fonte da contabilidade; a app nunca escreve nas tabelas dele.
- **ADR-002, autorização pela origem, sem espelho de acesso.** O livro autoriza títulos, baixas e lançamentos de regra pelo registro de origem desta app, então o acesso ao caixa basta para receber. As contas do livro de cada forma de pagamento ficam no caixa, resolvidas no `setup` por quem gere o livro. Mudar o vínculo de uma chave no livro depois exige refazer essa resolução.

## Consequences

- Quem altera o caixa recebe e emite recibo sem ler o livro; quem lê o livro vê os títulos e baixas.
- Toda coluna nova revisa `read_fields`, `personal_fields`, `sensitive_fields` e a migration de infraestrutura.
