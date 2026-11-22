# Evidência de testes

Só testes realmente executados, com comando, ambiente e resultado. Serviço indisponível é bloqueio de verificação, nunca aprovação por inferência. Cada epic acrescenta uma seção.

## Epic A: fundação (2026-11-17)

Local: Windows 11, Python 3.14, núcleo instalado do commit `f38c9a0`, PostgreSQL descartável do `dev_postgres.py` de um clone do núcleo, asserções na role runtime.

- `python -m pytest -q -n 4` → 40 passed, 3 subtests passed em 55 s.
- `python -m django check --fail-level WARNING` → sem problemas.
- `package doctor <pacote> --git-ref HEAD` nos quatro → `problems: []`.
- CI do PR alaorneto/medvita-core#50: lint, test (3.12 e 3.14), packages e CI verdes. Prova de reprovação: alaorneto/medvita-core#51 (fechado sem merge), run 44152427229 com `test_ci_must_fail` falhando.

## Epic B: `med_patients` (2026-11-17)

Mesmo ambiente.

- `python -m pytest -q -n 4` → suíte inteira verde (ver o PR do epic para o número final).
- `python -m django check --fail-level WARNING` e `makemigrations --check` → limpos.
- `tools/service_reference.py --check` e `tools/sync_leaves.py --check` → em dia.
- Contrato de tabela derivada do núcleo (`assert_derived_access_contract`) para `Patient`, `PatientGuardian` e `PatientCoverage`.

## Epic C: `med_scheduling` (2026-11-17)

Mesmo ambiente.

- `python -m pytest -q -n 4` → suíte inteira verde (número final no PR do epic).
- Contrato de tabela derivada do núcleo para `Professional`, `Room`, `AppointmentType`, `AvailabilityRule`, `ScheduleBlock` e `WaitlistEntry`; `Appointment` por testes próprios de autorização, isolamento A/B e observação (o preparo do kit não cria paciente).
- `med_scheduling/tests/unit/test_slots.py` e `test_transitions.py` (sem banco); páginas e API em `test_views.py` e `test_api.py`, com varredura de script inline, `style=` e `on*`.
- `python -m django check --fail-level WARNING`, `makemigrations --check`, `tools/service_reference.py --check` e `tools/sync_leaves.py --check` → limpos.

## Epic D: `med_records` (2026-11-17)

Mesmo ambiente.

- `python -m pytest -q -n 4` → suíte inteira verde (número final no PR do epic).
- Contrato de tabela derivada do núcleo, em `tests/test_derived_contracts.py` (a raiz monta o paciente que as tabelas exigem), para `PatientChart`, `Encounter`, `EncounterSection`, `Allergy`, `Medication`, `EntryTemplate`, `ClinicalDocument` e `AccessLog`, e também para `Appointment` da agenda.
- Contrato de selo do núcleo (`assert_sealed_contract`) para `Encounter` (com as seções) e `ClinicalDocument`.
- Validação de seções e troca de marcadores sem banco (`med_records/tests/unit`); páginas e API em `test_views.py` e `test_api.py`, com varredura de script inline, `style=`, `on*`, título sem o nome do paciente e `Cache-Control: no-store`.
- `python -m django check --fail-level WARNING`, `makemigrations --check`, `tools/service_reference.py --check` e `tools/sync_leaves.py --check` → limpos.

## Epic E: `med_finance` (2026-11-17)

Mesmo ambiente.

- `python -m pytest -q -n 4` → suíte inteira verde (número final no PR do epic).
- Contrato de tabela derivada do núcleo, em `tests/test_finance_contracts.py`, para `PriceItem`, `CashSession`, `CashMovement`, `Charge`, `ChargeItem`, `Payment`, `Receipt` e `ReceiptVoid`; contrato de selo para `Receipt`.
- Integração com o livro contábil provada pelos serviços do livro: título por conta, baixa por pagamento com estorno, lançamento por suprimento e sangria, saldo da conta de dinheiro igual ao resumo do dia.
- Valor por extenso sem banco (`med_finance/tests/unit`); páginas e API em `test_views.py`, com varredura de script inline, `style=` e `on*`.
- `python -m django check --fail-level WARNING`, `makemigrations --check`, `tools/service_reference.py --check` e `tools/sync_leaves.py --check` → limpos.

## Epic F: integração (2026-11-17)

- `tests/test_clinic_journey.py`: o dia inteiro da clínica pelos serviços públicos (cadastro, marcação, chegada, atendimento assinado, atestado, conta da consulta, Pix e dinheiro, recibos, fechamento do caixa), seguido da varredura de privacidade: nenhum nome, CPF, telefone, queixa ou alergia do cenário em eventos de domínio, evento do calendário, título do livro, auditoria (redigida) ou logs.
- `tests/test_isolation_matrix.py`: matriz papel × registro, organização B sem nada da A, escrita pelos contêineres, apps desligadas e paciente com registros não excluído.
- `tests/apps/med_example/tests/test_extension_points.py`: cada ponto de extensão das quatro apps usado por uma quinta app sem alterá-las.
- `med_patients/tests/test_clinic_setup.py` e `tests/test_demo_data.py`: a lista de configuração da clínica e o script de demonstração (roda uma vez; recusa fora de desenvolvimento e teste).
- Não rodou: o roteiro manual do guia de implantação num banco limpo, até a primeira consulta marcada; ele depende de um servidor com os pacotes instalados.

## Núcleo v0.3.0 (2026-11-21)

Local: Windows 11, Python 3.14, núcleo instalado da tag `v0.3.0` (commit `ce12e0c`), PostgreSQL descartável do `dev_postgres.py` de um clone do núcleo, asserções na role runtime.

- `python -m django check --fail-level WARNING` → sem problemas; `makemigrations --check --dry-run` → nada pendente.
- `python -m pytest -q -n 4` → 296 passed, 223 subtests passed.
- `package doctor <pacote>` nos quatro, sobre um commit da árvore de trabalho → `problems: []`.
- `tools/sync_leaves.py --check`, `tools/service_reference.py --check`, `ruff check .` e `ruff format --check .` → limpos.
- `/platform/appearance/` resolve (`platform:appearance`) e `appearance show` responde com a marca padrão num banco migrado.
