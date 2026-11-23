# Publicação

As quatro apps andam num trem de versão: têm sempre a mesma versão, escrita pela automação nos quatro `manifest.json`. Ninguém edita a versão nem o `CHANGELOG.md` à mão.

## Como uma versão sai

1. Um PR com o label `release` é aprovado e entra na `main`. O check "Verificação do PR" mostra antes a prévia da versão; a análise do diff acumulado (skill `dev-workflow`) decide se o nível sobe.
2. O workflow **Versão e release** (`.github/workflows/release.yml`) calcula o número, escreve a versão nos manifestos e nas faixas entre as apps (inclusive as da app de referência dos testes, `tests/apps/med_example`, que nunca é publicada), atualiza o `CHANGELOG.md`, cria a tag `v<versão>` e a GitHub Release.
3. O workflow **Publicação dos pacotes** (`.github/workflows/publish.yml`) roda quando a release é publicada: monta os quatro `.skapp` da tag, assina com a chave do publicador `katua-tech`, confere cada um (`tools/check_package.py` e `package validate`), monta o índice assinado e anexa pacotes, índice e chave pública à release.

## O que o responsável precisa ter feito

- **Release do núcleo.** Os manifestos apontam para o núcleo pela faixa `compatibility.skeleton`, e o CI e a publicação instalam o núcleo da tag de uma release publicada (`SKELETON_REF`, hoje `v0.4.0`). Subir o núcleo segue "Trocar o núcleo" em [desenvolvimento](development.md#ci).
- **Chave do publicador.** Gere com `python -m skeleton.system.packages keygen --private-key katua-tech.pem --public-key katua-tech.pub.pem` numa máquina confiável, fora do Git. Guarde o conteúdo da chave privada no secret `SKAPP_SIGNING_KEY` do repositório e o da chave pública na variável `SKAPP_PUBLIC_KEY`. A chave pública vai também para o trust store das instalações.
- **Permissão do workflow.** Em Settings → Actions → General, permita que o GitHub Actions crie e aprove pull requests, se o workflow de release precisar disso, e confira que `GITHUB_TOKEN` pode escrever conteúdo.

## Como conferir

- `gh run list --workflow release.yml --limit 1` e `gh run list --workflow publish.yml --limit 1` terminam com sucesso.
- A release tem os quatro `.skapp`, o `index.json` e a chave pública.
- Numa instalação limpa do núcleo, com a chave pública no trust store, os quatro pacotes passam em `package validate` e são instalados pelo fluxo de atualizações do núcleo.

## Ensaio

O job `packages` do CI ensaia a publicação a cada PR, com uma chave descartável do próprio job: monta os quatro pacotes da revisão commitada, confere o conteúdo, valida, inspeciona, extrai e monta e valida o índice. Nada é publicado.

## Desfazer

Uma versão publicada não é editada. Se um pacote saiu com defeito, corrija numa issue e publique a versão seguinte; para retirar a release, apague os anexos e a release no GitHub e registre o motivo. A tag não é reaproveitada.
