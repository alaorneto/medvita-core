# Desenvolvimento

Como preparar o ambiente, rodar os testes e criar migrations das quatro apps. As regras de implementação estão no `AGENTS.md`; este guia é só o procedimento.

## Ambiente

```text
medvita-core/         <- raiz do repositório git; não é pacote Python
  .venv/              <- virtualenv só deste repositório, com o núcleo instalado
  med_patients/  med_scheduling/  med_records/  med_finance/   <- um pacote por app
```

O núcleo entra no virtualenv como pacote instalado, nunca por cópia de código. Ele vem do repositório público do Skeleton, na tag de uma release publicada; a mesma tag está em `SKELETON_REF` no `.github/workflows/ci.yml` (hoje `v0.6.0`):

```bash
uv venv --python 3.14 .venv
uv pip install --python .venv/Scripts/python.exe "django-skeleton @ git+https://github.com/alaorneto/skeleton@<SKELETON_REF>"
uv pip install --python .venv/Scripts/python.exe pytest==9.2.0 pytest-django==4.14.0 pytest-xdist==3.8.0 ruff==0.17.4
```

Quando a release do núcleo anexar o wheel (`django_skeleton-<versão>-py3-none-any.whl`), a primeira instalação pode usá-lo no lugar da tag.

Para ler o código do núcleo, use o que está instalado em `.venv/Lib/site-packages/skeleton/` ou um clone do Skeleton na mesma tag.

## Variáveis

`tools/devenv.py` imprime as variáveis de desenvolvimento, com os caminhos absolutos calculados:

```bash
eval "$(python tools/devenv.py)"
```

No PowerShell: `python tools/devenv.py --powershell | Invoke-Expression`.

| Variável | Valor |
|---|---|
| `DJANGO_SETTINGS_MODULE` | `skeleton.testing.host.settings`: o projeto hospedeiro do núcleo, sem `config/` |
| `SKELETON_DEV_APPS` | os quatro pacotes, na ordem de carga: `med_patients`, `med_scheduling`, `med_records`, `med_finance` |
| `SKELETON_BUNDLED_APPS` | `calendar,ledger`: as apps first-party de que a agenda e o financeiro dependem |
| `SKELETON_TEST_ALLOW_SCHEMA_RESET` | `1`: autoriza recriar o schema do banco de teste |
| `TEST_DATABASE_URL` | banco de teste com a role `skeleton_runtime` (asserções) |
| `TEST_MIGRATION_DATABASE_URL` | o mesmo banco com a role `skeleton_owner` (migrations) |
| `SKELETON_TEST_PG_DUMP` | opcional: caminho do `pg_dump` da mesma versão do servidor |

As duas URLs têm senha: ficam no ambiente ou num `.env` na raiz, que o Git ignora e que os settings do hospedeiro leem. O script nunca as imprime.

## Banco de teste

O nome do banco termina em `_skeleton_test`, as migrations rodam como `skeleton_owner` e toda asserção roda como `skeleton_runtime`. Para provisionar num PostgreSQL que você administra, a partir do SQL que o núcleo distribui:

```bash
SKELETON_TEST_ADMIN_DATABASE_URL=postgres://postgres:<senha>@127.0.0.1:5432/postgres \
SKELETON_TEST_OWNER_PASSWORD=<senha do owner> SKELETON_TEST_RUNTIME_PASSWORD=<senha do runtime> \
python -m skeleton.testing.database provision --database med_skeleton_test
```

Para rodar em paralelo (`-n N`), provisione também um banco por worker: `med_gw0_skeleton_test` até `med_gw<N-1>_skeleton_test`. A fixture `skeleton_db` do `conftest.py` da raiz escolhe o banco do worker sozinha.

Sem PostgreSQL instalado, o script `dev_postgres.py` da pasta `tools` de um clone do Skeleton sobe um servidor descartável (sem Docker) com `local_skeleton_test` e um banco por worker (`--workers 8`); `python tools/dev_postgres.py env` mostra as URLs a copiar para o `.env`.

A fixture migra o schema uma vez por worker e, antes de cada teste, o recria a partir de um `pg_dump` dele. Sem `pg_dump`, ou com `MED_TEST_SCHEMA_TEMPLATE=0`, cada teste migra do zero, como a fixture do núcleo.

## Comandos

Todos a partir da raiz, com o virtualenv e as variáveis carregados.

| Para | Comando |
|---|---|
| Checks do Django e do núcleo | `python -m django check` |
| Criar migration | `python -m django makemigrations <label>`, depois `python -m django record_infrastructure <label> --write`, depois `migrations.leaves` do manifesto |
| Conferir que não falta migration | `python -m django makemigrations --check --dry-run` |
| Testes de uma app | `python -m pytest med_patients/tests -q` |
| Suíte inteira | `python -m pytest -q -n auto` |
| Lint | `ruff check .` e `ruff format --check .` |
| Diagnóstico de um pacote | `python -m skeleton.system.packages doctor med_patients --git-ref HEAD` (só enxerga o que está commitado) |

Se `python -m django <comando>` não achar um comando do núcleo com os settings do hospedeiro, é defeito a relatar, não a contornar copiando um `manage.py`.

## Servidor de desenvolvimento

O hospedeiro dos testes não serve páginas. Para navegar nas apps, use um clone do Skeleton como projeto e carregue os quatro pacotes por `SKELETON_DEV_APPS` (as mesmas variáveis acima, com `DJANGO_SETTINGS_MODULE=config.settings.development` e um `DATABASE_URL` de desenvolvimento), depois `python manage.py migrate` e `python manage.py runserver`. O `SKELETON_DEV_APPS` só vale nos perfis de desenvolvimento e teste.

## Versão

Ninguém edita `version` dos manifestos nem o `CHANGELOG.md`: a automação do `dev-workflow` escreve o mesmo número nos quatro manifestos e as faixas entre as apps (`.github/dev-workflow.toml`, `[[versioning.files]]`). O trem começa em 0.0.0; a primeira release sai 0.1.0.

## CI

`.github/workflows/ci.yml` roda em todo PR e push na `main`:

| Job | O que faz |
|---|---|
| `lint` | `ruff check .` e `ruff format --check .` |
| `test` | PostgreSQL 16 de serviço; instala o núcleo da tag `SKELETON_REF`; provisiona `ci_skeleton_test` e um banco por worker; `django check --fail-level WARNING`; `makemigrations --check`; `pytest -n 4`. Em Python 3.12 e 3.14 |
| `packages` | `package doctor <pacote> --git-ref HEAD` dos quatro pacotes |
| `CI` | agregador: falha se qualquer job falhar. É o check que o ruleset da `main` exige, ao lado de "Verificação do PR" |

Trocar o núcleo é uma mudança própria: suba na mesma mudança `SKELETON_REF` no `ci.yml` e no `publish.yml`, a faixa `compatibility.skeleton` dos manifestos (piso na versão da tag, teto no minor seguinte), as faixas de `org.skeleton.calendar` e `org.skeleton.ledger`, que acompanham a versão do núcleo, e os links fixados na tag (`AGENTS.md` da raiz, guia de implantação e `docs/service-api.md` de cada app). O job de publicação dos pacotes assinados não existe ainda: ele nasce com a primeira release, junto com o guia de publicação.

## PRs empilhados

Um epic com várias issues pode sair em PRs empilhados: a base de cada PR é a branch do anterior. O GitHub só fecha as issues citadas com `Closes`, `Fixes` ou `Resolves` quando o PR entra na branch padrão, então `.github/workflows/close-stacked-issues.yml` fecha as issues no merge de um PR empilhado, comenta em que PR e branch a entrega entrou e reconcilia o epic pai. `Refs #N` não fecha.

Mesclar um PR empilhado leva o código só para a branch de base. Para ele chegar à `main`, mescle a pilha de baixo para cima, apagando a branch de cada PR depois do merge (o GitHub então muda a base do PR seguinte para a `main`), ou abra no fim um PR da branch do topo para a `main`.

## Testes

| Fixture (`conftest.py` da raiz) | O que entrega |
|---|---|
| `skeleton_db` | O banco isolado da seção acima, com o schema recém-migrado e as asserções na role runtime |
| `clinic` | As organizações A e B com as quatro apps, `skeleton_calendar` e `skeleton_ledger` abertas e ativas; em cada uma, `admin` (dono), `reception`, `doctor` e `finance`, e os grupos Recepção, Profissionais de saúde e Financeiro (`clinic.a.groups["reception"]` etc.). `clinic.as_user(user, organization)` abre o contexto de requisição do ator. Nenhum contêiner: cada app cria os seus pelo próprio `setup` |

Regras:

- Pré-requisito de outra app se cria pelo serviço público dela (um paciente num teste da agenda nasce de `PatientService().create(...)`), nunca por `Model.objects.create` de outra app.
- Testes de leitura dividem um preparo com `subtests`. Nada de `sleep`, porta fixa, arquivo fora de `tmp_path` ou dependência de ordem: a suíte roda em paralelo.
- Toda asserção de isolamento roda na role runtime.
- O código das apps e os testes delas importam do núcleo só as superfícies públicas (o check W019 aponta o resto). `tests/support.py` é a exceção: monta pessoas, organizações e grupos com as funções de provisionamento que o próprio kit do núcleo usa, porque o kit ainda não tem um helper público para isso. Ele não entra em pacote nenhum.
