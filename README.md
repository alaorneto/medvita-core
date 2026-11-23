# Medvita Core

[![CI](https://github.com/alaorneto/medvita-core/actions/workflows/ci.yml/badge.svg)](https://github.com/alaorneto/medvita-core/actions/workflows/ci.yml)

Suíte proprietária de apps para consultórios e pequenas clínicas sobre o [Skeleton](https://github.com/alaorneto/skeleton). O repositório guarda as quatro apps do plano base; cada uma é publicada como um pacote `.skapp` assinado.

| Pacote e label | `app_id` | Nome exibido | Depende de |
|---|---|---|---|
| `med_patients` | `io.medvita.patients` | Pacientes | — |
| `med_scheduling` | `io.medvita.scheduling` | Agenda médica | Pacientes, agenda do núcleo (`org.skeleton.calendar`) |
| `med_records` | `io.medvita.records` | Prontuário | Pacientes, Agenda médica |
| `med_finance` | `io.medvita.finance` | Financeiro | Pacientes, Agenda médica, livro contábil do núcleo (`org.skeleton.ledger`) |

O núcleo não é copiado para cá: ele vem instalado no ambiente virtual (wheel de uma release ou commit fixo do repositório do Skeleton).

## Como implantar

Veja o [guia de implantação](docs/deployment-guide.md): apps do núcleo, pacotes, CID-10, grupos, a lista "Configuração da clínica" e os dados de demonstração.

## Como desenvolver

Veja `docs/development.md` (ambiente, variáveis, banco de teste e comandos). As regras para agentes e desenvolvedores estão no `AGENTS.md`.

## Licença

Software proprietário da Katuá Tech. Todos os direitos reservados; veja `LICENSE`.
