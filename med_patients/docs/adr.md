# Pacientes: decisões

## Context

O paciente é base de todas as outras apps da suíte e a equipe inteira da clínica precisa escrever nele, mas uma concessão de registro do núcleo só vale no próprio registro e só o administrador concede acesso. CPF nem sempre existe (recém-nascidos, estrangeiros) e não pode ser chave.

## Decision

- **ADR-001, paciente é tabela derivada do cadastro.** O `PatientRegistry` é o único `SecuredRecord` exposto e decide o acesso de tudo que a app guarda (`TableSpec.access_parent`). A recepção ganha escrita no cadastro uma vez, no `setup`, e a partir daí cria e altera pacientes sem nova concessão.
- **ADR-002, CPF opcional e único entre os vivos.** O código do paciente (`P` + sequência sem lacunas) é a identidade comercial; o CPF, quando informado, é único por organização entre os cadastros vivos (restrição única parcial), e um paciente excluído libera o CPF.
- **ADR-003, as linhas do paciente seguem o paciente.** Responsáveis, convênios e consentimentos apontam para o paciente com relação reversa oculta: a exclusão lógica do paciente não esbarra neles, a autorização derivada os esconde junto, e a restauração os traz de volta sem recriar nada.

## Consequences

- Quem tem `update` no cadastro altera qualquer paciente dele; regras mais finas (restrição de tratamento, anonimização) são do serviço e só restringem.
- Uma clínica que quer cadastros separados cria outro `PatientRegistry` com outra concessão; o `setup` cria só o padrão.
- Toda coluna nova revisa `read_fields`, `personal_fields` e a migration de infraestrutura.
