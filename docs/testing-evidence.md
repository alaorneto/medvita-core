# Evidência de testes

Só testes realmente executados, com comando, ambiente e resultado. Serviço indisponível é bloqueio de verificação, nunca aprovação por inferência. Cada epic acrescenta uma seção.

## Epic A: fundação (2026-11-17)

Local: Windows 11, Python 3.14, núcleo instalado do commit `f38c9a0`, PostgreSQL descartável do `dev_postgres.py` de um clone do núcleo, asserções na role runtime.

- `python -m pytest -q -n 4` → 40 passed, 3 subtests passed em 55 s.
- `python -m django check --fail-level WARNING` → sem problemas.
- `package doctor <pacote> --git-ref HEAD` nos quatro → `problems: []`.
- CI do PR alaorneto/sk_med_core#50: lint, test (3.12 e 3.14), packages e CI verdes. Prova de reprovação: alaorneto/sk_med_core#51 (fechado sem merge), run 44152427229 com `test_ci_must_fail` falhando.

## Epic B: `med_patients` (2026-11-17)

Mesmo ambiente.

- `python -m pytest -q -n 4` → suíte inteira verde (ver o PR do epic para o número final).
- `python -m django check --fail-level WARNING` e `makemigrations --check` → limpos.
- `tools/service_reference.py --check` e `tools/sync_leaves.py --check` → em dia.
- Contrato de tabela derivada do núcleo (`assert_derived_access_contract`) para `Patient`, `PatientGuardian` e `PatientCoverage`.
