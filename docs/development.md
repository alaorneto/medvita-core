# Desenvolvimento

Como preparar o ambiente, rodar os testes e criar migrations das quatro apps. As regras de implementação estão no `AGENTS.md`; este guia é só o procedimento.

## Ambiente

```text
sk_med_core/          <- raiz do repositório git; não é pacote Python
  .venv/              <- virtualenv só deste repositório, com o núcleo instalado
  med_patients/  med_scheduling/  med_records/  med_finance/   <- um pacote por app
```

O núcleo entra no virtualenv como pacote instalado, nunca por cópia de código. Enquanto o núcleo não tem release publicada, ele vem de um commit fixo do repositório público do Skeleton; o mesmo commit está em `SKELETON_REF` no `.github/workflows/ci.yml`:

```bash
uv venv --python 3.14 .venv
uv pip install --python .venv/Scripts/python.exe "django-skeleton @ git+https://github.com/alaorneto/skeleton@<SKELETON_REF>"
uv pip install --python .venv/Scripts/python.exe pytest==9.2.0 pytest-django==4.14.0 pytest-xdist==3.8.0 ruff==0.17.4
```

Com release publicada, troque a primeira instalação pelo wheel da release (`django_skeleton-<versão>-py3-none-any.whl`) e suba a faixa `compatibility.skeleton` dos quatro manifestos na mesma mudança.

Para ler o código do núcleo, use o que está instalado em `.venv/Lib/site-packages/skeleton/` ou um clone do Skeleton no mesmo commit.

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

Sem PostgreSQL instalado, o `tools/dev_postgres.py` de um clone do Skeleton sobe um servidor descartável (sem Docker) com `local_skeleton_test` e um banco por worker (`--workers 8`); `python tools/dev_postgres.py env` mostra as URLs a copiar para o `.env`.

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
