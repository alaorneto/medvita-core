# Prontuário: decisões

## Context

O sigilo médico exige que só a equipe assistencial de um paciente leia o prontuário, enquanto a recepção marca e recebe; uma clínica pode ter prontuário único ou cada profissional o seu. A lei pede guarda de 20 anos e nenhum registro assinado pode mudar.

## Decision

- **ADR-001, o arquivo clínico como unidade de sigilo.** `Archive` é o único contêiner; prontuários, atendimentos, listas, documentos e a trilha derivam dele. Quem lê o arquivo lê tudo dele; a recepção não recebe concessão. Uma clínica com prontuário único usa um arquivo `shared`; profissionais que não compartilham usam arquivos `personal`.
- **ADR-002, retenção por guarda registrada.** A guarda legal é uma função registrada em `med_patients` (`register_retention_guard`), consultada na exclusão e na anonimização do paciente; ela lê os prontuários da organização corrente sem ampliar o acesso.
- **ADR-003, selo no lugar de assinatura digital.** Assinar um atendimento é selá-lo pelo núcleo: o banco recusa qualquer mudança e o resumo SHA-256 cobre o conteúdo, as referências e as seções. O plano base não tem certificado ICP-Brasil nem o nível NGS2 da certificação SBIS; uma app de assinatura assinará o `seal_digest` sem tocar nas tabelas. As referências do atendimento ficam fora de `seal_fields` porque já são imutáveis desde a criação (`immutable_fields`); o resumo as cobre pelo `extra`.

## Consequences

- Mudar quem lê um prontuário é conceder ou revogar no arquivo, nunca no prontuário.
- Toda coluna nova revisa `read_fields`, `personal_fields`, `sensitive_fields` e a migration de infraestrutura.
