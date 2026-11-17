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
| Dado sensível (saúde) | `TableSpec.sensitive_fields` | `[REDACTED]` na auditoria; fora de eventos e de DTOs, salvo método que documente | conteúdo das seções da evolução, texto de documento clínico, alergia, medicamento, CID, observações da consulta |

- Payload de evento, snapshot de notificação e título de evento da agenda nunca levam dado pessoal nem de saúde: levam `sysid`, código comercial e situação.
- Nada é apagado fisicamente. Paciente com prontuário não é excluído nem anonimizado antes do fim da guarda; a regra é implementada por guardas de retenção registradas pelas apps.
- A leitura de prontuário é registrada numa trilha própria do `med_records`: a auditoria do núcleo só cobre escrita.

## O que o produto cobre

Preenchido por epic, à medida que as entregas chegam.

## O que o produto não cobre

- Assinatura digital ICP-Brasil nem nível de garantia NGS2 do prontuário: os registros definitivos são selados (imutáveis, com resumo SHA-256) e trazem o aviso de ausência de assinatura digital.
- Receita de medicamentos sujeitos a controle especial (SNCR).
- Faturamento TISS, NFS-e e o Receita Saúde.
- Telemedicina.

## Pendências do negócio

Fora do software, a resolver pelo responsável:

1. Responsável técnico médico da plataforma e inscrição no CRM (Resolução CFM 2.299/2021).
2. Texto jurídico definitivo da licença proprietária.
3. Prazo de guarda fiscal de contas e recibos, a confirmar com o contador.
