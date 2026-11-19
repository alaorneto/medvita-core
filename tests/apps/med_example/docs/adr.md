# Exemplo de extensão: decisões

## Context

Os pontos de extensão das quatro apps precisam de uma prova executável.

## Decision

Uma app de teste que só importa o `service_api` das quatro e as superfícies públicas do núcleo.

## Consequences

Se um mecanismo exigir mudança numa das quatro apps, a prova falha e a mudança vira issue da app dona.
