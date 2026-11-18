# Arquitetura

A suíte é um repositório com quatro apps do Skeleton. Cada app é um pacote publicado sozinho (`.skapp`), contratado sozinho e ativado por organização; as quatro andam num só trem de versão.

## Árvore do repositório

```text
sk_med_core/                      <- raiz do repositório git; não é pacote Python
  AGENTS.md  LICENSE  README.md  pyproject.toml  conftest.py
  .github/                        <- dev-workflow, CI, modelos de issue e PR
  .claude/skills/dev-workflow/    <- cópia instalada pelo bootstrap
  docs/                           <- documentação da suíte
  tools/                          <- scripts de desenvolvimento (nunca empacotados)
  tests/                          <- cenários que cruzam as apps
  med_patients/                   <- pacote; o nome do diretório é o package_name
    AGENTS.md  .gitattributes  LICENSE  manifest.json
    apps.py  registration.py  models.py  policies.py  services.py
    service_api.py  extension.py  forms.py  views.py  urls.py  api_urls.py
    migrations/  templates/med_patients/  static/med_patients/
    docs/spec.md  docs/adr.md  docs/service-api.md
    tests/
  med_scheduling/  med_records/  med_finance/      <- mesma forma
```

- O `.gitattributes` que vale no empacotamento é o de cada pacote: `package build --app-root <pacote> --git-ref <rev>` exporta só a subárvore, com as regras dela. `AGENTS.md` e o próprio `.gitattributes` ficam fora do pacote.
- Nenhum arquivo de `config/` nem cópia do núcleo entra no repositório.
- `extension.py` guarda os registries que a app oferece; `service_api.py` os reexporta, porque é o único módulo que outra app pode importar.
- `policies.py` guarda os atalhos de autorização da app, sempre sobre `authorized_queryset` e `require_record_action`.

## Identidade das apps

| Pacote e label | `app_id` | Nome exibido | `dependencies` |
|---|---|---|---|
| `med_patients` | `io.katua.sk.med.patients` | Pacientes | — |
| `med_scheduling` | `io.katua.sk.med.scheduling` | Agenda médica | `io.katua.sk.med.patients`, `org.skeleton.calendar` |
| `med_records` | `io.katua.sk.med.records` | Prontuário | `io.katua.sk.med.patients`, `io.katua.sk.med.scheduling` |
| `med_finance` | `io.katua.sk.med.finance` | Financeiro | `io.katua.sk.med.patients`, `io.katua.sk.med.scheduling`, `org.skeleton.ledger` |

Comum aos quatro manifestos: `manifest_version: 2`, `kind: "app"`, `publisher: "katua-tech"` (exibido como Katuá Tech), `app_config: "applications.<pacote>.apps.<Classe>Config"`, a mesma `version`, a mesma faixa `compatibility.skeleton`, `lifecycle` com retenção dos dados, manutenção e backup, `runtime.default_enabled: false` e `runtime.documentation_root: "docs"`. As faixas entre as apps da suíte usam a própria versão (`>=0.1.0,<0.2.0` na primeira linha), escritas pela automação.

Ordem de carga em `SKELETON_DEV_APPS` (a de `INSTALLED_APPS`): `med_patients`, `med_scheduling`, `med_records`, `med_finance`. First-party ligadas: `SKELETON_BUNDLED_APPS=calendar,ledger`.

## Dependências

```text
                 med_patients
                 ▲    ▲     ▲
                 │    │     │
   skeleton_calendar  │     │
          ▲           │     │
          │           │     │
     med_scheduling ──┘     │
       ▲        ▲           │
       │        │           │
 med_records   med_finance ─┘──► skeleton_ledger
```

A seta aponta para a app de que se depende. No sentido da seta, uma app chama o `service_api` da outra. No sentido contrário, a app de baixo publica eventos de domínio e oferece registries; a de cima consome os eventos e se registra no `ready()`.

## Integração entre as apps

| Mecanismo | Sentido | Exemplos |
|---|---|---|
| API de serviços | da app que depende para a dependência | a agenda lê o paciente com `PatientService().summary(...)` |
| Eventos de domínio do núcleo | da dependência para quem depende | o financeiro cria a conta ao receber `med_scheduling.appointment_completed` |
| Registries exportados pelo `service_api` | quem depende se registra na dependência | a agenda põe a aba "Consultas" na página do paciente |
| FK `PROTECT` por texto | integridade no banco | `Appointment.patient` aponta para `"med_patients.Patient"`; o banco impede excluir paciente com consulta |

Uma FK entre apps nunca é caminho de leitura: o dado da outra app vem do serviço dela, que autoriza.

## Regras comuns de implementação

- **Camadas:** `views.py`/`api_urls.py` → `service_api.py` (contrato, DTOs, autorização) → `services.py` (regras internas) → `models.py`.
- **Bases:** contêiner é `SecuredRecord`; filho é `OrganizationRecord` com `access_parent`; registro definitivo usa `SealableMixin`, e os filhos dele `seal_parent`. Nenhuma tabela `OperationalRecord` (é do núcleo).
- **Relações:** `PROTECT` sempre; a FK do contêiner e a de `seal_parent` em `immutable_fields`. Nunca M2M implícito: tabela de ligação explícita.
- **Dinheiro:** inteiro da menor unidade (`skeleton.common.money`), nunca `float` nem `Decimal` em coluna de valor.
- **Datas:** `DateTimeField` com fuso; DTO em UTC; a superfície converte para o fuso do consultório.
- **Migrations:** `makemigrations <label>`, depois `record_infrastructure <label> --write`, depois `migrations.leaves` do manifesto. Migration publicada numa release nunca é editada; nenhuma extensão, função, view ou trigger próprios.
- **Texto:** todo texto visível por gettext com msgid em pt-BR; identificadores em inglês; docstrings de `service_method` com `Autorização:`, `Erros:` e `Efeitos:`.
- **Interface:** só as classes de componente do núcleo e o CSS próprio da app; sem `<script>` inline, `style=` ou `on*=`. Título `<tela> · {{ site_name }}`.
- **Testes:** todo método de serviço com o kit `skeleton.testing.service_api`; toda tabela com o checklist do núcleo; tabela derivada com `skeleton.testing.derived`; registro selado com `skeleton.testing.sealing`; PostgreSQL com a role runtime.
- **Versão:** ninguém edita `version` dos manifestos nem o changelog.
