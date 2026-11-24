# med_patients: Pacientes

Regras do núcleo: `AGENTS.md` do Skeleton (link no [`AGENTS.md` da raiz](../AGENTS.md)). Regras da suíte: [`../AGENTS.md`](../AGENTS.md). Este arquivo só traz o que é próprio desta app.

## Propósito e limites

Cadastro do paciente como registro da organização (nunca um usuário): identificação, contatos, responsáveis, convênios, consentimentos LGPD e os pontos de extensão da página do paciente. É a base das outras três apps.

**Não faz:** dado clínico (é do `med_records`), valores e cobrança (`med_finance`), agenda (`med_scheduling`), fusão de cadastros duplicados, portal do paciente.

## Tabelas

- Contêiner `PatientRegistry` (o cadastro da clínica).
- Derivadas: `Patient` (do cadastro), `PatientGuardian`, `PatientCoverage` e `Consent` (do paciente), `ImportBatch` (do cadastro).
- Todo campo de identificação, contato, endereço e observação é `personal_fields`. Nenhum campo é `sensitive_fields`: não há dado de saúde aqui.

## Serviços e pontos de extensão

- Oferece `PatientService` e os registries `register_patient_section`, `register_summary_panel`, `register_timeline_provider`, `register_consent_purpose`, `register_retention_guard`, `register_patient_data_provider` e `register_setup_step` (`docs/extension-points.md` da raiz).
- Publica `patient_created`, `patient_updated`, `patient_status_changed` e `consent_changed`.
- Consome só serviços do núcleo.

## Invariantes do domínio

1. O código do paciente (`P` + 6 dígitos) vem da sequência sem lacunas e nunca muda.
2. CPF é opcional e único entre os cadastros vivos da organização.
3. Exclusão e anonimização consultam todas as guardas de retenção; um veto impede a operação.
4. Paciente com tratamento restrito não muda; paciente anonimizado é somente leitura para sempre.
5. Mensagem de erro e log citam o campo, nunca o valor.

## Testes e especificação

- Testes: `python -m pytest med_patients/tests -q -n auto` a partir da raiz, com o ambiente de `docs/development.md`.
- Especificação: `docs/spec.md`, decisões em `docs/adr.md` e contrato do serviço em `docs/service-api.md`, todos neste pacote.
