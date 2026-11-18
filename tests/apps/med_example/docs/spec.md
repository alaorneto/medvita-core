# Exemplo de extensão

App de referência dos testes do repositório. Nunca é publicada.

## Contract

Um quadro (`ExampleBoard`, contêiner) com notas sobre pacientes (`ExampleNote`, derivada). Consome `med_scheduling.appointment_completed` e `med_records.encounter_signed` e grava uma nota por evento. Registra uma aba, um provedor de linha do tempo, uma finalidade de consentimento, uma guarda de retenção, um provedor de relatório do titular, um passo de configuração, uma ação de consulta, um tipo de seção, um tipo de documento e uma origem de conta.

## Acceptance

- Cada ponto de extensão funciona com a app ativa e some com ela desativada.
