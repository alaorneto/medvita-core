# med_records: Prontuário

Regras do núcleo: `AGENTS.md` do Skeleton (link no [`AGENTS.md` da raiz](../AGENTS.md)). Regras da suíte: [`../AGENTS.md`](../AGENTS.md). Este arquivo só traz o que é próprio desta app.

## Propósito e limites

Registro clínico: prontuário do paciente por arquivo clínico, atendimentos com seções estruturadas, assinatura por selo, adendos, alergias, medicamentos em uso, CID-10, modelos, documentos simples, anexos e trilha de leitura.

**Não faz:** assinatura digital ICP-Brasil, receita de controlados, laudo de exame, telemedicina.

## Tabelas

- Contêiner `Archive` (arquivo clínico da clínica ou de um profissional).
- Derivadas: `PatientChart` (do arquivo); `Encounter`, `Allergy`, `Medication`, `ClinicalDocument` e `AccessLog` (do prontuário); `EncounterSection` (do atendimento); `EntryTemplate` (do arquivo).
- Global, não exposta: `Icd10Code`.
- Seladas: `Encounter` (com `EncounterSection`) e `ClinicalDocument`.
- Todo conteúdo clínico é `sensitive_fields`.

## Serviços e pontos de extensão

- Oferece `RecordsService` e os registries `register_section_type` e `register_document_kind`.
- Publica `encounter_signed` e `document_issued`, com o `seal_digest`.
- Consome `PatientService`, `SchedulingService` e os serviços de selo, arquivos e eventos do núcleo.
- Contribui para outras apps em `registration.py` e `integration.py`: guarda de retenção, passo de configuração, ação "Atender" nas consultas, aba "Prontuário" (só para quem lê um arquivo), linha do tempo e relatório do titular.
- Superfícies: páginas em `views.py` (todas `never_cache`) e API REST só de leitura em `api.py`; nenhuma consulta modelo.
- As referências dos registros selados (prontuário, paciente, autor, consulta, adendo) ficam fora de `seal_fields`, porque já são imutáveis; o resumo as cobre pelo `extra` (`seal_extra`, `document_extra`). Não acrescente uma coluna a `seal_fields` e a `immutable_fields` ao mesmo tempo.

## Invariantes do domínio

1. Atendimento ou documento assinado não muda nem é excluído; correção é adendo ou substituição.
2. Rascunho só é alterado e descartado pelo autor.
3. Conteúdo clínico nunca aparece em auditoria, evento, notificação, log, linha do tempo ou erro.
4. Toda leitura de conteúdo clínico grava a trilha de leitura.
5. Nada é apagado antes de 20 anos do último registro do prontuário.
6. Título de página, URL, mensagem e nome de arquivo nunca levam o nome do paciente nem conteúdo clínico; o texto clínico é mostrado escapado, nunca com `|safe`.

## Testes e especificação

- Testes: `python -m pytest med_records/tests -q -n auto` a partir da raiz, com o ambiente de `docs/development.md`.
- Especificação: `docs/spec.md`, decisões em `docs/adr.md` e contrato do serviço em `docs/service-api.md`, todos neste pacote.
