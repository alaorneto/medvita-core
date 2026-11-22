# Prontuário

O registro clínico do consultório: arquivos clínicos, o prontuário de cada paciente, atendimentos com seções estruturadas selados na assinatura, adendos, alergias, medicamentos em uso, CID-10, modelos, documentos simples, anexos e a trilha de leitura. A app **não** faz assinatura digital ICP-Brasil, receita de controlados, laudo de exame nem telemedicina.

## Contract

### Ativação e dependências

Depende de `io.katua.sk.med.patients` (o paciente de cada prontuário) e de `io.katua.sk.med.scheduling` (a ficha do profissional que assina e a consulta atendida). Instalada globalmente e ativada por organização, depois das dependências.

### Acesso

Um contêiner (`SecuredRecord` exposto): `Archive`, o arquivo clínico, unidade de sigilo. Todo o resto deriva dele, direto ou pelo prontuário: ler pede `read` no arquivo, escrever pede `update`. A recepção não recebe concessão em arquivo nenhum e por isso não lê conteúdo clínico.

O `setup` (capacidade `access.manage`) tem dois modos:

- `shared`: um arquivo padrão da clínica, privado e do administrador, lido e escrito pelos grupos informados (em geral, Profissionais de saúde).
- `per_professional`: um arquivo pessoal para cada profissional ativo vinculado a uma pessoa, do qual a pessoa é dona; ninguém mais o lê.

Em ambos, o papel `member` recebe leitura e alteração da tabela de arquivos (quem decide são as concessões por registro). `create_archive` cria outros arquivos (uma especialidade, um profissional novo).

### Modelo de dados

**`Archive`** (contêiner): `name`, `kind` (`shared` ou `personal`, imutável), `is_default` (um por organização).

**`PatientChart`** (derivada do arquivo): `archive` e `patient` (imutáveis; um prontuário vivo por arquivo e paciente), `opened_at`, `last_entry_at` (o último registro clínico, base da guarda legal).

**`Encounter`** (derivada do prontuário, selável): `chart`, `patient`, `code` (`E` + 8 dígitos da sequência `med_records.encounter`), `kind` (consulta, retorno, procedimento, contato a distância, anotação, adendo), `occurred_at` (não futura), `author` (a pessoa), `author_name` e `author_council` (fotografia na assinatura; `personal_fields`), `appointment` (opcional), `amends` (só no adendo). As referências (`chart`, `patient`, `author`, `appointment`, `amends`) são imutáveis desde a criação; o selo congela `code`, `kind`, `occurred_at`, `author_name` e `author_council`, e o resumo cobre também as referências e as seções.

**`EncounterSection`** (derivada do atendimento, três saltos até o arquivo; `seal_parent` do atendimento): `section_type` e `type_version`, `position`, `data` (JSON) e `text`, ambos em `sensitive_fields`. Uma seção viva por tipo e posição.

**`Allergy`** (derivada do prontuário): `substance` e `reaction` (`sensitive_fields`), `category` (medicamento, alimento, ambiental, outra), `severity` (leve, moderada, grave, não informada), `status` (ativa, resolvida, descartada), `noted_on`.

**`Medication`** (derivada do prontuário): `name`, `dose`, `frequency` e `note` (`sensitive_fields`), `route`, `started_on`, `ended_on` (não antes do início), `status` (em uso, suspenso, encerrado).

**`Icd10Code`** (`SystemRecord` global, não exposta): `code` (único), `description`, `is_category`, `search_text` (normalizado). Sem dado de organização; escrita só pelo comando `load_icd10`.

**`EntryTemplate`** (derivada do arquivo): `name`, `specialty`, `kind` (atendimento ou documento), `sections` (seções validadas pelo tipo), `document_kind` e `body` (para documento), `author` (preenchido: modelo pessoal, só o autor vê e altera), `is_active`.

**`ClinicalDocument`** (derivada do prontuário, selável): `code` (`D` + 8 dígitos da sequência `med_records.document`), `kind` (tipo registrado), `title` e `body` (`sensitive_fields`), `issued_at`, `author`, `author_name` e `author_council` (fotografia na emissão), `encounter` (opcional), `replaces` (documento substituído). O selo congela código, tipo, título, texto, emissão e autor; o resumo cobre as referências.

**`AccessLog`** (derivada do prontuário, nunca muda): `actor`, `action` (leitura do prontuário, de atendimento, de documento, impressão, download de anexo, exportação), `target_table`, `target_id`, `at`.

Anexos (PDF, JPEG, PNG, até 20 MB) ficam no armazenamento privado do núcleo, no prontuário (exames e documentos externos) ou num atendimento em rascunho (o selo os cobre depois).

### Prontuário

`open_chart` obtém ou cria o prontuário do paciente: exige alteração no arquivo e leitura do paciente. Sem `archive_id` usa o arquivo padrão que o ator altera, ou o único; com vários e nenhum padrão, pede o arquivo. `chart` e `charts_for_patient` não devolvem conteúdo clínico.

### Atendimentos em rascunho

- `start_encounter` cria um rascunho do ator (alteração no arquivo). Com uma consulta, confere que é do mesmo paciente e, se ela está em "chegou", tenta iniciá-la na agenda; a recusa da agenda não impede o rascunho.
- Só o autor altera ou descarta o rascunho; os outros leitores do arquivo o veem marcado "rascunho, não assinado".
- `save_section` valida pelo tipo de seção, usa a revisão do **atendimento** como CAS (cada seção salva sobe a revisão) e atualiza `last_entry_at` do prontuário. `remove_section` e `discard_draft` são exclusões lógicas; atendimento assinado responde `Conflict("signed")`.
- `encounters` devolve só cabeçalhos; `encounter` devolve o conteúdo e registra a leitura na trilha.
- O conteúdo das seções sai `[REDACTED]` na auditoria.

### Assinatura, adendo e verificação

- `sign_encounter`: só o autor, com pelo menos uma seção preenchida (`Conflict("empty")`) e uma ficha de profissional com conselho na agenda (`Conflict("professional_required")`). Grava `author_name` e `author_council` da ficha, sela o atendimento (`skeleton.records.sealing.seal_record`, com as referências e as seções no `extra`) e publica `med_records.encounter_signed`. Com a consulta vinculada em atendimento, tenta concluí-la; a recusa da agenda não desfaz a assinatura e `appointment_completed` diz o que aconteceu.
- Depois de assinado, nada muda: seções, exclusão e anexos novos são recusados pelo serviço e pelo guard do banco. **Não há assinatura digital ICP-Brasil**: o selo é o resumo SHA-256 do conteúdo, que uma app de assinatura poderá assinar.
- `add_addendum`: qualquer profissional que altera o arquivo cria um rascunho `addendum` com texto livre apontando para o original assinado; assina-se pelo mesmo `sign_encounter`. O original nunca muda e lista os adendos assinados.
- `verify_encounter` recalcula o resumo a partir do conteúdo gravado.
- A ação "Atender" (`med_records.attend`) aparece nas consultas em "chegou" e "em atendimento".

### Alergias, medicamentos e resumo

`allergies` lista as ativas primeiro (as graves antes); `medications`, as em uso primeiro. Alterar a situação é `update_allergy` / `update_medication` com CAS; a auditoria guarda o histórico com o conteúdo redigido. `chart_summary` reúne as alergias ativas, os medicamentos em uso e os cinco últimos cabeçalhos de atendimento. Toda leitura dessas listas grava a trilha.

### Modelos e documentos

- `create_template` grava um modelo de atendimento (seções validadas) ou de documento (texto com marcadores) no arquivo; `personal=True` o deixa só para o autor. `update_template` altera ou desativa (`active=False`), com CAS. `start_encounter(template_id=...)` cria as seções do modelo; `draft_document(template_id=...)` usa o texto dele.
- `draft_document` cria o rascunho com o texto do modelo ou do tipo, trocando os marcadores pelo nome de exibição do paciente, a data no fuso do consultório e o nome do profissional. Só o autor altera (`update_document`).
- `issue_document`: só o autor, com texto e ficha de profissional com conselho; grava a emissão e o autor, sela e publica `med_records.document_issued` (sem título nem texto). Emitido, não muda.
- `replace_document` cria um rascunho com o mesmo conteúdo e `replaces`; emitido o novo, o antigo aparece "substituído por <código>" e continua íntegro (`verify_document`).
- A receita simples traz o aviso de que não serve para medicamentos sujeitos a controle especial.

### CID-10

O repositório não distribui a tabela CID-10. O operador baixa a oficial (DATASUS), converte para um CSV `code;description` e roda `python -m django load_icd10 <arquivo.csv> --confirm` (sem `--confirm`, só valida). O arquivo inteiro é validado antes de gravar (código `^[A-Z][0-9]{2}(\.[0-9])?$`, descrição de 1 a 300 caracteres, sem código repetido), numa transação: uma linha inválida aborta tudo e o erro diz o número da linha. Rodar de novo só atualiza descrições.

`search_icd10` busca por prefixo de código (`J45`) ou pelas palavras da descrição sem acento (`asma`), até 50 resultados, para qualquer ator com a app ativa. Sem catálogo carregado, o formulário de diagnóstico aceita código e descrição digitados (validação só de formato); a seção guarda `code` e `description` como fotografia, nunca uma FK. Limite conhecido: a tabela é global e o núcleo não impede a role runtime de escrevê-la; nenhum serviço, página ou API da app escreve nela, só o comando.

### Trilha de leitura e anexos

- A auditoria do núcleo só cobre escrita; a leitura de conteúdo clínico (`encounter`, `document`, `chart_summary`, `allergies`, `medications`, `attachment_url`) grava uma linha em `AccessLog` depois de autorizada, escrita pelo serviço (quem lê só precisa de leitura), com a origem da requisição (`origin`: `web`, `native_client` com o `client_id`, `api_token` ou `other`). A mesma pessoa lendo o mesmo alvo pela mesma origem em menos de 5 minutos gera uma linha só.
- `access_log` exige a gestão de acesso do arquivo (dono ou administrador): o profissional comum não lê a trilha. A linha não tem caminho de alteração nem de exclusão; o guard do banco recusa mudança.
- `attach_to_chart` e `attach_to_encounter` anexam (atendimento assinado: `Conflict("signed")`, anexe ao prontuário); `attachments` lista; `attachment_url` confere que o anexo é do alvo, devolve o endereço reautorizado pelo núcleo a cada download e grava a trilha. Revogada a concessão no arquivo, o endereço para de funcionar.

### Página do paciente

- Aba "Prontuário" (`med_records.chart`, ordem 30), visível só para quem lê algum arquivo clínico (`PatientSection.visible`): a recepção não a vê.
- Linha do tempo: "Atendimento registrado" e "Documento emitido", sem tipo de documento nem conteúdo, só do que o ator lê.
- Relatório do titular: data, código e profissional de cada atendimento assinado e documento emitido legível. O conteúdo clínico integral não entra no relatório automático: a cópia do prontuário é entregue pelo profissional, pela impressão dos registros.

### Tipos de seção e de documento

Cada seção de um atendimento é de um tipo registrado (`register_section_type`): campos estruturados validados por `validate_section` (chave desconhecida, tipo errado, valor fora da faixa, opção fora da lista e dois diagnósticos principais são recusados; decimais viram texto com ponto) e, quando o tipo aceita, texto livre de até 50.000 caracteres. A seção gravada guarda a versão do tipo; o formulário usa a maior.

| Código | Campos estruturados |
|---|---|
| `med_records.anamnesis` | queixa principal, história da doença atual, antecedentes pessoais e familiares, hábitos |
| `med_records.vitals` | pressão sistólica (30–300 mmHg) e diastólica (20–200), frequências cardíaca (20–300 bpm) e respiratória (4–80), temperatura (30–45 °C), saturação (50–100 %), peso (0,3–500 kg), altura (20–260 cm), glicemia (10–1000 mg/dL); o IMC é calculado na exibição, nunca gravado |
| `med_records.physical_exam` | só texto |
| `med_records.assessment` | diagnósticos CID-10 (código, descrição, no máximo um principal) |
| `med_records.plan` | só texto |
| `med_records.evolution` | subjetivo, objetivo, avaliação e plano |
| `med_records.free_text` | só texto |

Tipos de documento básicos (`register_document_kind`): atestado, declaração de comparecimento, receita simples (com o aviso de que não serve para medicamentos sujeitos a controle especial), pedido de exame e encaminhamento. O texto padrão aceita os marcadores `{{patient_name}}`, `{{date}}` e `{{professional_name}}`, trocados por `render_placeholders` sem motor de templates: qualquer outro texto fica literal.

### Guarda legal

O prontuário é guardado por 20 anos depois do último registro (Lei 13.787/2018, constante `RETENTION_YEARS` em `retention.py`). A guarda registrada em `med_patients` (`med_records.retention`) veta excluir ou anonimizar o paciente enquanto houver prontuário com registro nesse prazo; resta a restrição de tratamento. A guarda roda no contexto da organização de quem pediu, sem abrir outro.

### Páginas

Em `/o/<org>/apps/med_records/` (nomes `med_records:<nome>`); toda leitura e escrita passa pelo `RecordsService`. As páginas clínicas respondem `Cache-Control: no-store`; o título nunca leva o nome do paciente; o texto clínico é escapado, com as quebras de linha por CSS.

| Nome | Página |
|---|---|
| `home`, `setup` | Arquivos clínicos legíveis; configuração inicial (administradores) |
| `patient_section` | Aba "Prontuário" do paciente: escolha do arquivo, abrir prontuário, alergias em destaque, medicamentos, atendimentos, documentos, anexos, novo atendimento e novo documento |
| `attend` | Entrada pela consulta: abre o prontuário e retoma (ou inicia) o rascunho da consulta |
| `encounter`, `encounter_print` | Leitura do atendimento: seções, selo ("sem assinatura digital ICP-Brasil"), adendos, anexos; versão de impressão |
| `encounter_edit` | Editor do rascunho: um cartão por seção com o próprio botão, busca de CID-10 por GET, anexos, salvar como modelo, assinar e descartar; funciona sem JavaScript |
| `addendum` | Cria o rascunho de um adendo |
| `lists` | Alergias e medicamentos, com inclusão e mudança de situação |
| `document_edit`, `document`, `document_print`, `document_replace` | Rascunho, leitura, impressão (dados do consultório, código, resumo do selo e o aviso) e substituição do documento |
| `templates` | Modelos do arquivo e pessoais; novo modelo de documento |
| `access_log` | Trilha de leitura (dono do arquivo e administrador) |

### API REST

Em `/api/v1/o/<org>/apps/med_records/`, só leitura (a escrita clínica é só pelas páginas), sempre com `Cache-Control: no-store`:

| Método e caminho | O que faz | Token |
|---|---|---|
| `GET charts/?patient=` | Prontuários do paciente nos arquivos legíveis (`ChartInfo`) | `records:read` |
| `GET charts/<id>/encounters/?cursor=&page_size=` | Cabeçalhos dos atendimentos (`EncounterHeader`, sem conteúdo) | `records:read` |
| `GET encounters/<id>/` | Atendimento com as seções (`EncounterInfo`); grava a trilha | `records:read` |
| `GET documents/<id>/` | Documento com o texto (`DocumentInfo`); grava a trilha | `records:read` |

Toda rota aceita a sessão do navegador e o token de um cliente fora dele (o access token OIDC de um cliente nativo, como o Medvita Desktop, ou um token `skt_`) nos métodos da coluna "Token", com as mesmas respostas, filtros, `ETag`, `If-Match` e `Idempotency-Key` da sessão. O escopo só restringe: o serviço autoriza o papel da pessoa como para a sessão, e um token com o escopo continua sem ver o que o papel não alcança. O token amplo (`openid profile email`) leva todos os escopos; um cliente que o operador limitou (`native_client register --scope`) precisa do escopo da coluna e do escopo de tabela do contêiner que o serviço autoriza (`med_records.archive:read`). Sem o escopo, a resposta é 403 `permission_denied` ("O token não tem o escopo exigido."); método fora da coluna é 403 `token_not_allowed`. Cada operação aparece no `/api/v1/openapi.json` só para quem pode chamá-la.

Com token, só `GET`: `POST`, `PATCH`, `PUT` e `DELETE` são sempre 403 `token_not_allowed`, e não há escopo de escrita. Cada leitura de conteúdo clínico grava na trilha a origem: sessão web, cliente nativo (com o `client_id`), token de API ou outra.

## Acceptance

- A recepção não lê arquivo nem prontuário: `chart` responde `NotFound`, `charts_for_patient` é vazio e `open_chart` é recusado.
- Com dois arquivos pessoais, um profissional não lê o prontuário do outro para o mesmo paciente.
- `open_chart` repetido devolve o mesmo prontuário; a organização B não vê nada da A.
- Com registro clínico recente, anonimizar o paciente é recusado com o motivo da guarda; passados os 20 anos, é aceito.
- Assinado, o atendimento recusa seção nova, exclusão e anexo; `verify_encounter` confirma o selo e acusa conteúdo diferente do selado.
- O evento `encounter_signed` não leva conteúdo clínico.
- Pelas páginas, o profissional abre o prontuário, inicia um atendimento, salva seções, assina, vê o selo, escreve um adendo, emite e imprime um atestado.
- A recepção recebe 404 em todas as páginas clínicas e não vê a aba "Prontuário".
- Texto com `<script>` digitado numa seção sai escapado na leitura e na impressão.
