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

### Prontuário

`open_chart` obtém ou cria o prontuário do paciente: exige alteração no arquivo e leitura do paciente. Sem `archive_id` usa o arquivo padrão que o ator altera, ou o único; com vários e nenhum padrão, pede o arquivo. `chart` e `charts_for_patient` não devolvem conteúdo clínico.

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

## Acceptance

- A recepção não lê arquivo nem prontuário: `chart` responde `NotFound`, `charts_for_patient` é vazio e `open_chart` é recusado.
- Com dois arquivos pessoais, um profissional não lê o prontuário do outro para o mesmo paciente.
- `open_chart` repetido devolve o mesmo prontuário; a organização B não vê nada da A.
- Com registro clínico recente, anonimizar o paciente é recusado com o motivo da guarda; passados os 20 anos, é aceito.
