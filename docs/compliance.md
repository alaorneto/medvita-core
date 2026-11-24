# Conformidade

> Este documento não é parecer jurídico. Confira o texto oficial antes de afirmar conformidade.

O que o produto faz e o que não faz em relação às normas que se aplicam a um consultório. Cada epic atualiza a seção do que entregou.

## Normas de referência

| Norma | Assunto |
|---|---|
| Resolução CFM 2.299/2021 | Prontuário eletrônico e responsabilidade técnica da plataforma |
| Resolução CFM 2.314/2022 | Telemedicina |
| Lei 13.787/2018 | Digitalização e guarda do prontuário (20 anos a partir do último registro) |
| Lei 13.709/2018 (LGPD) | Tratamento de dados pessoais e de dados pessoais sensíveis (saúde) |
| RDC Anvisa 1.000/2025 | Receituário e controle especial |
| Padrão TISS (ANS) | Troca de informações com operadoras |

## Dados pessoais e de saúde

| Classe | Onde se declara | Efeito | Exemplos |
|---|---|---|---|
| Dado pessoal | `TableSpec.personal_fields` | Legível pela API; `[REDACTED]` na auditoria | nome, CPF, RG, CNS, telefone, email, endereço, nome da mãe |
| Dado sensível (saúde) | `TableSpec.sensitive_fields` | `[REDACTED]` na auditoria; fora de eventos e de DTOs, salvo método que documente | conteúdo das seções da evolução, texto de documento clínico, alergia, medicamento, CID, observações da consulta, marca de prioridade na fila, descrição de um item consumido no atendimento |

- Payload de evento, snapshot de notificação e título de evento da agenda nunca levam dado pessoal nem de saúde: levam `sysid`, código comercial e situação.
- **Calendário externo.** O que sai da suíte para o aplicativo de calendário de uma pessoa (o arquivo `.ics` baixado e o link de assinatura de um calendário, os dois do núcleo) é só o que a agenda projeta: o tipo e o código da consulta, a contagem de pacientes de um período de ordem de chegada e "Bloqueio". Esses títulos saem para o dono da agenda e para quem marcou; os outros leitores recebem "Ocupado". Nome, documento, telefone, observação e prioridade do paciente não saem para ninguém. O link é pessoal, vale um ano, é revogado em Tokens de API e para de responder quando a pessoa deixa de ler a agenda; a suíte não gera, não guarda e não registra o segredo dele, que viaja no caminho do endereço do feed do núcleo (o proxy da instalação o tira dos logs, como pede o guia de implantação do núcleo). O código da consulta num aparelho pessoal só identifica o paciente para quem já lê a agenda.
- **Itens consumidos e dados fiscais.** O evento `items_consumed` leva a referência opaca do item que a app dona escolheu, nunca a descrição (uma vacina diria por que o paciente veio) nem o paciente. Nome e CPF do pagador, do paciente e do profissional para um documento fiscal saem só pelo serviço do financeiro (`fiscal_data`), para quem lê o caixa, nunca em evento.
- **Portal do paciente.** A pessoa externa vê só as agendas publicadas, os nomes dos profissionais e os horários livres, e marca só para os pacientes que a app do portal ligou a ela. A auditoria e o evento `appointment_booked` registram a pessoa como ator, com `source="http:portal"`.
- A marca de prioridade legal da fila (Lei 10.048) permite inferir idade, gestação ou deficiência: é dado sensível, guardada sem o motivo, e sai só na fila e no detalhe da consulta, para quem lê a agenda.
- Nada é apagado fisicamente. Paciente com prontuário não é excluído nem anonimizado antes do fim da guarda; a regra é implementada por guardas de retenção registradas pelas apps.
- A leitura de prontuário é registrada numa trilha própria do `med_records`: a auditoria do núcleo só cobre escrita.
- **Computador compartilhado do balcão.** Os campos de dado pessoal (nome, CPF, CNS, telefone, email, endereço) e as buscas de paciente levam `autocomplete="off"`, para o navegador não guardar no histórico de formulário o que foi digitado de um paciente e oferecer ao próximo; os números abrem o teclado numérico (`inputmode`) e os telefones são `type="tel"` (#120). Limite conhecido: as buscas de paciente são GET, e o termo digitado (nome, CPF ou telefone) vai na URL da busca; os logs do proxy devem descartar a query string dessas rotas.
- **Anonimização vetada.** A aba Privacidade consulta as guardas de retenção antes da tentativa (`PatientService.anonymization_vetoes`) e, havendo veto, mostra o motivo no lugar do formulário; `anonymize` consulta de novo ao gravar (#134).
- **Ações irreversíveis.** Cancelar, marcar falta, assinar, emitir, anular, estornar, fechar o caixa, revogar e remover passam por uma página de confirmação com o alvo e a consequência, com a mesma autorização da ação: quem não alcança o alvo recebe o mesmo 404 no GET e no POST (#119).

## O que o produto cobre

### Consentimento

O tratamento de dados para a assistência à saúde em si tem base legal própria (tutela da saúde) e não depende de consentimento. O `med_patients` registra consentimento para finalidades adicionais, declaradas em código pelas apps (por exemplo `med_patients.contact`, contato por telefone, mensagem e email): quem coletou, como (presencial, papel, digital, verbal), a versão do termo e o termo digitalizado anexo. Revogar guarda a linha com a hora; conceder de novo cria outra linha, então o histórico de cada finalidade é completo.

### Direitos do titular

O `med_patients` gera o relatório dos dados de um paciente (cadastro, responsáveis, convênios, consentimentos e as seções que as outras apps declaram), restringe o tratamento e anonimiza o cadastro quando nenhuma guarda de retenção veta. Limites:

- A geração do relatório não altera dado e por isso não entra na auditoria do núcleo: fica só no log estruturado da aplicação, com os identificadores do paciente e de quem gerou.
- O relatório automático não traz o conteúdo clínico integral: a cópia do prontuário é entregue pelo profissional, pela impressão dos registros.
- A anonimização é irreversível e só acontece fora dos prazos de guarda declarados pelas apps.

### Prontuário assinado

O atendimento assinado é selado: o banco recusa qualquer mudança nele e nas suas seções, e a correção é um adendo também selado. O resumo SHA-256 do selo e a data e o autor da assinatura aparecem no registro. Isso garante integridade e autoria dentro do sistema, **não** a assinatura digital com certificado ICP-Brasil que o CFM exige para dispensar o papel (ver abaixo).

### Trilha de leitura do prontuário

Toda leitura de conteúdo clínico pelo sistema é registrada (quem, o quê, quando), com uma linha por pessoa e alvo a cada 5 minutos; só o dono do arquivo clínico ou o administrador a consulta. Limites: leituras feitas fora do sistema (cópia impressa, acesso direto ao banco por quem administra a infraestrutura) não entram na trilha, e a cópia integral do prontuário para o titular é entregue pelo profissional, não pelo relatório automático.

### Recibos

Os recibos do financeiro são numerados por ano sem lacunas, selados na emissão e anulados por registro, nunca editados. Eles comprovam o pagamento ao paciente, mas **não** substituem documento fiscal: NFS-e e o Receita Saúde ficam fora do plano base.

## O que o produto não cobre

- Assinatura digital ICP-Brasil nem nível de garantia NGS2 do prontuário: os registros definitivos são selados (imutáveis, com resumo SHA-256) e trazem o aviso de ausência de assinatura digital.
- Receita de medicamentos sujeitos a controle especial (SNCR).
- Faturamento TISS, NFS-e e o Receita Saúde.
- Telemedicina.

## Pendências do negócio

- Confirmar com o contador o prazo de guarda dos registros financeiros (o produto veta anonimizar o paciente com conta dos últimos 5 anos).


Fora do software, a resolver pelo responsável:

1. Responsável técnico médico da plataforma e inscrição no CRM (Resolução CFM 2.299/2021).
2. Texto jurídico definitivo da licença proprietária.
3. Prazo de guarda fiscal de contas e recibos, a confirmar com o contador.
