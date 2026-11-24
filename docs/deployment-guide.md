# Guia de implantação

Para o operador da plataforma e para o administrador da clínica. As regras de instalação, atualização e operação do núcleo estão na documentação do Skeleton ([implantação](https://github.com/alaorneto/skeleton/blob/v0.8.0/docs/deployment.md) e [atualizações](https://github.com/alaorneto/skeleton/blob/v0.8.0/docs/updates.md)); este guia só cobre o que é próprio da suíte.

## 1. Operador da plataforma

1. Ligue as apps first-party de que a suíte depende: `SKELETON_BUNDLED_APPS=calendar,ledger`.
2. Instale os quatro pacotes (`med_patients`, `med_scheduling`, `med_records`, `med_finance`), nesta ordem, pelo fluxo de pacotes `.skapp` do núcleo, com a chave pública do publicador `katua-tech` no trust store.
3. Torne as apps disponíveis para a organização da clínica (calendário, livro contábil e as quatro).
4. Carregue a tabela CID-10, que o repositório não distribui: baixe a oficial do DATASUS, converta para um CSV `code;description` (uma linha por código, como `J45.0;Asma predominantemente alérgica`) e rode:

   ```bash
   python -m django load_icd10 cid10.csv            # só valida
   python -m django load_icd10 cid10.csv --confirm  # grava; repetir só atualiza descrições
   ```

5. Com a cobrança da plataforma ligada, cadastre no catálogo de cobrança os produtos das quatro apps e os planos (seção 4).
6. Ative a marca Medvita: instalar a suíte não ativa o tema. Em `/platform/appearance/`, na tabela "Temas de apps", pré-visualize o tema "Medvita" (da app Pacientes) e clique em "Ativar". Ele troca as cores nos modos claro e escuro, os títulos (Poppins), o logo, o ícone, o nome do produto e o rodapé da instância; a marca própria de cada clínica continua valendo nas telas dela. Pelo console: `python manage.py appearance show` mostra o tema ativo. Uma instância que prefere enviar o pacote encontra o `medvita-theme-<versão>.zip` anexado à release. Desinstalar o `med_patients` tira o tema do catálogo e a instância volta ao tema do núcleo (a prévia de desinstalação avisa).

## 2. Administrador da clínica

1. Ative as apps na organização (calendário e livro contábil antes das quatro).
2. Crie os grupos na tela de acesso do núcleo (`/o/<org>/access/`) e ponha as pessoas neles. O núcleo não tem serviço para criar grupos; a suíte espera:
   - **Recepção**: cadastra pacientes, marca consultas, recebe no caixa.
   - **Profissionais de saúde**: atendem e escrevem no prontuário.
   - **Financeiro**: preços, caixa e relatórios.
3. Abra a lista "Configuração da clínica" (`/o/<org>/apps/med_patients/setup/clinic/`) e siga os passos na ordem:
   1. **Pacientes**: o cadastro, escrito pela Recepção e pelos Profissionais, lido pelo Financeiro.
   2. **Agenda médica**: o consultório, lido por todos os grupos e gerido pela Recepção (que também cuida da lista de espera).
   3. **Prontuário**: um arquivo da clínica para os Profissionais, ou um arquivo por profissional (depois de cadastrar os profissionais vinculados às pessoas).
   4. **Financeiro**: o caixa (Recepção e Financeiro recebem) e a tabela de preços (o Financeiro altera); o livro contábil padrão é criado e preparado.
4. Em **Agenda médica → Configuração**, cadastre os profissionais (vinculados às pessoas, com conselho e número: só eles assinam atendimentos e documentos), as salas e os tipos de atendimento. O código de cobrança de cada tipo é o código do item na tabela de preços.
5. Em **Agenda médica → Agendas**, crie a agenda de cada profissional e a grade semanal. Na mesma página, cada pessoa assina no celular o calendário das agendas que lê ("Assinar no celular": um link por pessoa e calendário, criado na página do calendário), e "Calendários compartilhados" leva à página em que a clínica cria os calendários comuns (reuniões, férias, plantões).
6. Em **Financeiro → Preços**, cadastre os itens com os códigos de cobrança.
7. Confira, no livro contábil, o plano de contas e as chaves do financeiro (receita de atendimentos, dinheiro, Pix, cartões, banco, aportes e retiradas).

## 3. O que cada grupo consegue fazer

| Grupo | Pacientes | Agenda | Prontuário | Financeiro |
|---|---|---|---|---|
| Recepção | cadastra e altera | marca, recebe a chegada, gere a lista de espera | nada | abre e fecha o caixa, recebe, emite recibo |
| Profissionais de saúde | cadastra e altera | vê as agendas em que tem acesso | lê e escreve; assina o que escreve | nada |
| Financeiro | lê | vê a configuração | nada | recebe, altera preços, relatórios |
| Administrador | tudo, inclusive privacidade | tudo | tudo, inclusive a trilha de leitura | tudo |

## 4. Planos e limites

Os preços e os limites são dados do catálogo de cobrança da plataforma, nunca código. Sugestão de planos: **Solo** (1 profissional ativo), **Consultório** (até 5), **Clínica** (até 15). O medidor `med_scheduling.active_professionals` conta os profissionais ativos e limita o cadastro e a reativação quando a cobrança está ligada; `med_patients.active_patients` só mede.

## 5. Dados de demonstração

Num ambiente de desenvolvimento, com as quatro apps configuradas numa organização sem pacientes:

```bash
python tools/demo_data.py --org <slug> --as <e-mail de um administrador> --confirm
```

O script cria profissionais, salas, tipos particulares e de convênio, agendas com grade (a do segundo profissional atende por ordem de chegada à tarde), pacientes fictícios, consultas com hora e por ordem de chegada, a fila de hoje quando é dia útil, atendimentos assinados e contas, só pelos serviços públicos. Ele recusa rodar fora dos perfis de desenvolvimento e teste e numa organização que já tenha paciente.

## 6. Ao atualizar uma clínica que já tem agendas

A partir do núcleo `v0.4.0`, o calendário de cada agenda de atendimento é gerenciado pela agenda médica: as páginas do calendário não o renomeiam, compartilham nem excluem, e o acesso dele só muda junto com o da agenda. As agendas criadas depois da atualização já nascem assim. Para as que existiam antes, quem gerencia o acesso abre **Agenda médica → Agendas** e usa "Vincular à agenda médica" uma vez; o aviso some quando não há mais nada a vincular, e repetir o passo não muda nada. Até lá as agendas funcionam como antes, só que a página do calendário ainda deixa mudar o acesso do calendário sem mudar o da agenda.

## 7. Ao atualizar para o núcleo `v0.6.0`

A partir do núcleo `v0.6.0`, o MFA é exigido em produção do administrador da plataforma (sem como desligar) e, por padrão, de quem tem papel administrativo na organização (`SKELETON_REQUIRE_ADMIN_MFA`, na tela da instância). Até cadastrar o autenticador, essas pessoas só veem as páginas de MFA. Avise o administrador da clínica antes de atualizar. Como a clínica guarda dado de saúde, vale também ligar a política da organização para todos os membros (**Configurações → Segurança**, `mfa_policy=all`); quem perder o autenticador e os códigos de recuperação é atendido pelo administrador da plataforma, que redefine o MFA. As regras estão na autenticação da documentação do [núcleo v0.6.0](https://github.com/alaorneto/skeleton/blob/v0.6.0/docs/authentication-sso.md#mfa-cifrado-e-obrigatório).

## 8. Ao atualizar para o núcleo `v0.8.0`

O agente não pula uma linha minor do núcleo: de `0.6.x` o caminho é `0.6.x → 0.7.0 → 0.8.0`, cada passo com as migrations dele ([atualizações](https://github.com/alaorneto/skeleton/blob/v0.8.0/docs/updates.md)). Instale a suíte compatível com a `v0.8.0` só depois do último passo. A partir da `v0.7.0`, a agenda e o livro contábil do núcleo são bibliotecas first-party instaladas sozinhas com as apps que as exigem, e os avisos (como "Paciente chegou") têm texto de fábrica que a organização pode ligar, desligar e editar em **Configurações → Notificações** ([notificações](https://github.com/alaorneto/skeleton/blob/v0.8.0/docs/notifications.md)).
