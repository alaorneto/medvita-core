# Instruções para agentes: suíte Medvita Core

## Contrato do núcleo

Tudo que é do núcleo (bases de modelo, `TableSpec`, autorização, contexto, auditoria, exclusão, API de serviços, migrations, testes e rastreabilidade) está no `AGENTS.md` do Skeleton, que vale integralmente aqui e não é repetido: <https://github.com/alaorneto/skeleton/blob/v0.4.0/AGENTS.md>. A referência é a tag da release do núcleo instalada (`SKELETON_REF` em `.github/workflows/ci.yml`), que é a versão mínima de `compatibility.skeleton` dos manifestos e é atualizada na mesma mudança que sobe a faixa. A documentação do núcleo (`docs/` do mesmo repositório e da mesma referência) completa o contrato. Em divergência entre este arquivo e o do núcleo, vale o do núcleo.

Este arquivo guarda só o que é comum às quatro apps. O que é de uma app está no `AGENTS.md` dela.

## Ordem de leitura

1. `README.md` e este arquivo.
2. `docs/architecture.md`, `docs/access-model.md`, `docs/extension-points.md` e `docs/compliance.md`.
3. `docs/development.md` antes de rodar qualquer comando.
4. O `AGENTS.md` da app em que vai trabalhar e a `docs/spec.md` dela.

## Fronteiras do repositório

- A raiz não é pacote Python. Cada app é um diretório com o nome do pacote e o `manifest.json` na raiz dele: `med_patients`, `med_scheduling`, `med_records`, `med_finance` (árvore e identidades em `docs/architecture.md`).
- Dependências entre as apps só no sentido `med_patients` ← `med_scheduling` ← `med_records`, e `med_finance` sobre pacientes e agenda. A agenda usa `org.skeleton.calendar` e o financeiro `org.skeleton.ledger`. Toda dependência está declarada em `dependencies` do manifesto.
- Uma app só importa de outra o `service_api` dela. O sentido contrário ao da dependência é feito por eventos de domínio do núcleo e pelos registries que cada app exporta no `service_api` (`docs/extension-points.md`).
- `tests/` da raiz guarda os cenários que cruzam apps; `tools/` guarda scripts de desenvolvimento, que nunca entram num pacote.

## Regras da suíte

- **Camadas de uma app:** views e API chamam o `service_api.py`; ele autoriza, monta DTOs e chama `services.py`, que trabalha nos modelos. Views nunca consultam modelo.
- **Acesso por contêiner:** cada app tem um ou dois contêineres (`SecuredRecord` exposto); toda outra tabela é derivada do contêiner (`TableSpec.access_parent`). Regra de serviço além do contêiner só restringe (`docs/access-model.md`).
- **Relações entre apps:** FK `PROTECT` por texto (`"med_patients.Patient"`) para integridade; o dado da outra app é lido sempre pelo serviço dela, nunca pela relação.
- **Dinheiro** em inteiros da menor unidade (`skeleton.common.money`). **Datas** com fuso; DTO em UTC.
- **Texto visível** por gettext com msgid em pt-BR; identificadores, modelos, campos e métodos em inglês.
- **Interface:** só as classes de componente do núcleo e o CSS próprio em `static/<label>/<label>.css`; JavaScript só em arquivo estático e opcional (a página funciona sem ele).
- **Dados pessoais e de saúde:** campo pessoal em `personal_fields`; conteúdo clínico em `sensitive_fields`. Nenhum dado pessoal ou de saúde em payload de evento, snapshot de notificação, título de evento da agenda, log, mensagem de erro, URL ou nome de arquivo: esses levam `sysid`, código e situação.
- **Retenção:** nada é apagado fisicamente. Exclusão e anonimização de paciente passam pelas guardas de retenção registradas pelas apps (`docs/compliance.md`).
- **Testes** usam a fixture `skeleton_db` do `conftest.py` da raiz e a `clinic` (organizações A/B da clínica); pré-requisito de outra app nasce pelo serviço público dela.

## Rastreabilidade

O skill `dev-workflow` (`.claude/skills/dev-workflow/`, configurado em `.github/dev-workflow.toml`) vale aqui como no núcleo. Próprio deste repositório:

- Issues e PRs têm a seção "Segurança e contrato do AGENTS.md"; o label `security` marca impacto em isolamento, autorização, dados de saúde, auditoria ou segredos.
- As quatro apps andam num só trem de versão: a automação escreve o mesmo número nos quatro manifestos e prende ao minor corrente as faixas entre elas. Ninguém edita `version` nem o changelog.
- Um PR por epic; cada epic parte da branch do anterior enquanto o anterior não está na `main`.

## Proibido

- Copiar código do núcleo para o repositório, ou importar módulo do núcleo fora das superfícies públicas (o check W019 aponta).
- Abrir `system_context` num serviço de app, usar SQL cru ou relação reversa sem filtro.
- Excluir fisicamente qualquer registro.
- Acrescentar biblioteca de terceiros sem issue própria.
