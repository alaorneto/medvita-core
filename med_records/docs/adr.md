# Prontuário: decisões

## Context

O sigilo médico exige que só a equipe assistencial de um paciente leia o prontuário, enquanto a recepção marca e recebe; uma clínica pode ter prontuário único ou cada profissional o seu. A lei pede guarda de 20 anos e nenhum registro assinado pode mudar.

## Decision

- **ADR-001, o arquivo clínico como unidade de sigilo.** `Archive` é o único contêiner; prontuários, atendimentos, listas, documentos e a trilha derivam dele. Quem lê o arquivo lê tudo dele; a recepção não recebe concessão. Uma clínica com prontuário único usa um arquivo `shared`; profissionais que não compartilham usam arquivos `personal`.
- **ADR-002, retenção por guarda registrada.** A guarda legal é uma função registrada em `med_patients` (`register_retention_guard`), consultada na exclusão e na anonimização do paciente; ela lê os prontuários da organização corrente sem ampliar o acesso.

## Consequences

- Mudar quem lê um prontuário é conceder ou revogar no arquivo, nunca no prontuário.
- Toda coluna nova revisa `read_fields`, `personal_fields`, `sensitive_fields` e a migration de infraestrutura.
