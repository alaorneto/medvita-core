# Financeiro

Especificação inicial gerada por `skeleton_startapp`. Substitua cada parágrafo pelo comportamento real da app antes do primeiro release; o check E012 verifica apenas a presença das seções, não a qualidade do conteúdo. Veja [apps e instalação](../../../docs/concepts.md#apps-pacotes-e-deployment) e o roteiro de [extensão](../../../docs/extending.md).

## Contract
`med_finance` é instalada globalmente e ativada por organização; instalar o código não concede permissões. A app nasce indisponível e desativada: a plataforma concede a disponibilidade e cada organização ativa explicitamente (`default_enabled` é obsoleto e fica `false`).

Cada `CashDesk` pertence a uma organização e deriva de `SecuredRecord`: UUID imutável, revisão, proprietário e visibilidade. Os campos de negócio são `code` (até 64 caracteres, único entre registros vivos da organização) e `title` (até 200). Nenhum campo é sensível; declare em `sensitive_fields` qualquer campo novo cujo valor não possa aparecer na auditoria.

O gateway usa `med_finance.cashdesk` com criação, leitura, alteração, exclusão lógica e restauração conforme `TablePermission` e a autorização do registro. Alterar, excluir ou restaurar exige a revisão atual.

A página própria fica em `/o/<org>/apps/med_finance/` e o sumário em `/api/v1/o/<org>/apps/med_finance/summary/`. Ambos exigem app ativa e `table.read`, e contam somente registros legíveis pelo ator.

Outras apps consomem esta só por `CashDeskService`, declarada em `runtime.service_api` e documentada em [service-api.md](service-api.md). Página e sumário chamam o mesmo serviço, que devolve DTOs imutáveis e revalida a autorização.

## Acceptance
Critérios observáveis a confirmar por testes reais (não por inferência):

- Com organizações A/B, um membro de A não obtém registros de B em lista, detalhe, contagem, sumário, auditoria ou restauração, inclusive por UUID conhecido.
- Sem `table.read`, página e sumário são negados; com ela, o sumário exclui registros privados de terceiros.
- Duas alterações com a mesma revisão não vencem ambas.
- Restaurar um registro cujo `code` colide com outro vivo retorna conflito sem sobrescrevê-lo.
