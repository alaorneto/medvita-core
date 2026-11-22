# Changelog

Todas as mudanças publicadas deste projeto. Este arquivo é escrito pela automação de release; não edite as seções de versão à mão.

## [0.1.0](https://github.com/alaorneto/medvita-core/releases/tag/v0.1.0) — 2026-11-22

### ⚠ Mudanças incompatíveis

- bring epics B to F to main (PR [#59](https://github.com/alaorneto/medvita-core/pull/59)) — `med_finance/migrations/0001_initial.py` alterado em «Migrations das apps»; `med_finance/migrations/0002_record_infrastructure.py` alterado em «Migrations das apps»; `med_patients/migrations/0001_initial.py` alterado em «Migrations das apps»; `med_patients/migrations/0002_record_infrastructure.py` alterado em «Migrations das apps»; `med_records/migrations/0001_initial.py` alterado em «Migrations das apps»; `med_records/migrations/0002_record_infrastructure.py` alterado em «Migrations das apps»; `med_scheduling/migrations/0001_initial.py` alterado em «Migrations das apps»; `med_scheduling/migrations/0002_record_infrastructure.py` alterado em «Migrations das apps»
- rename the app identifiers from io.katua.sk.med to io.medvita (PR [#72](https://github.com/alaorneto/medvita-core/pull/72)) — `!` em deef98b: rename the app identifiers from io.katua.sk.med to io.medvita; BREAKING CHANGE em deef98b: the app_id of every app changes. A manifest that depends; `!` em título do PR: rename the app identifiers from io.katua.sk.med to io.medvita; label `breaking-change`; O app_id das quatro apps muda de io.katua.sk.med.<app> para io.medvita.<app>; um manifesto que dependa do id antigo precisa declarar o novo. Nenhuma versão tinha sido publicada com os ids antigos.

### Funcionalidades

- Gerar as quatro apps vazias, o ambiente de desenvolvimento e o trem de versão ([#3](https://github.com/alaorneto/medvita-core/issues/3)) — PR [#50](https://github.com/alaorneto/medvita-core/pull/50)
- Criar o cadastro `PatientRegistry`, a tabela `Patient` e o `setup` ([#8](https://github.com/alaorneto/medvita-core/issues/8)) — PR [#59](https://github.com/alaorneto/medvita-core/pull/59)
- Implementar o serviço de pacientes: criar, buscar, alterar, situação, excluir e restaurar ([#9](https://github.com/alaorneto/medvita-core/issues/9)) — PR [#59](https://github.com/alaorneto/medvita-core/pull/59)
- Adicionar responsáveis e convênios do paciente ([#10](https://github.com/alaorneto/medvita-core/issues/10)) — PR [#59](https://github.com/alaorneto/medvita-core/pull/59)
- Adicionar consentimentos LGPD com finalidades registráveis ([#11](https://github.com/alaorneto/medvita-core/issues/11)) — PR [#59](https://github.com/alaorneto/medvita-core/pull/59)
- Oferecer os pontos de extensão da página do paciente ([#12](https://github.com/alaorneto/medvita-core/issues/12)) — PR [#59](https://github.com/alaorneto/medvita-core/pull/59)
- Criar as páginas e a API REST de pacientes ([#13](https://github.com/alaorneto/medvita-core/issues/13)) — PR [#59](https://github.com/alaorneto/medvita-core/pull/59)
- Importar pacientes por CSV ([#14](https://github.com/alaorneto/medvita-core/issues/14)) — PR [#59](https://github.com/alaorneto/medvita-core/pull/59)
- Atender os direitos do titular e fechar a documentação de `med_patients` ([#15](https://github.com/alaorneto/medvita-core/issues/15)) — PR [#59](https://github.com/alaorneto/medvita-core/pull/59)
- Criar consultório, profissionais, salas e tipos de atendimento ([#17](https://github.com/alaorneto/medvita-core/issues/17)) — PR [#59](https://github.com/alaorneto/medvita-core/pull/59)
- Criar agendas ligadas ao calendário, com grade e bloqueios ([#18](https://github.com/alaorneto/medvita-core/issues/18)) — PR [#59](https://github.com/alaorneto/medvita-core/pull/59)
- Calcular horários livres ([#19](https://github.com/alaorneto/medvita-core/issues/19)) — PR [#59](https://github.com/alaorneto/medvita-core/pull/59)
- Marcar, encaixar, remarcar e cancelar consultas com projeção no calendário ([#20](https://github.com/alaorneto/medvita-core/issues/20)) — PR [#59](https://github.com/alaorneto/medvita-core/pull/59)
- Implementar o fluxo de atendimento da consulta e as ações registráveis ([#21](https://github.com/alaorneto/medvita-core/issues/21)) — PR [#59](https://github.com/alaorneto/medvita-core/pull/59)
- Adicionar a lista de espera ([#22](https://github.com/alaorneto/medvita-core/issues/22)) — PR [#59](https://github.com/alaorneto/medvita-core/pull/59)
- Criar as páginas da agenda e integrar com a página do paciente ([#23](https://github.com/alaorneto/medvita-core/issues/23)) — PR [#59](https://github.com/alaorneto/medvita-core/pull/59)
- Criar a API REST da agenda e fechar a documentação de `med_scheduling` ([#24](https://github.com/alaorneto/medvita-core/issues/24)) — PR [#59](https://github.com/alaorneto/medvita-core/pull/59)
- Criar arquivo clínico, prontuário do paciente e guarda de retenção ([#26](https://github.com/alaorneto/medvita-core/issues/26)) — PR [#59](https://github.com/alaorneto/medvita-core/pull/59)
- Registrar tipos de seção e de documento com validação ([#27](https://github.com/alaorneto/medvita-core/issues/27)) — PR [#59](https://github.com/alaorneto/medvita-core/pull/59)
- Criar o atendimento em rascunho com tabelas seláveis ([#28](https://github.com/alaorneto/medvita-core/issues/28)) — PR [#59](https://github.com/alaorneto/medvita-core/pull/59)
- Assinar atendimentos por selo, com adendo e verificação ([#29](https://github.com/alaorneto/medvita-core/issues/29)) — PR [#59](https://github.com/alaorneto/medvita-core/pull/59)
- Adicionar alergias, medicamentos em uso e o resumo do prontuário ([#30](https://github.com/alaorneto/medvita-core/issues/30)) — PR [#59](https://github.com/alaorneto/medvita-core/pull/59)
- Adicionar o catálogo CID-10 e os diagnósticos ([#31](https://github.com/alaorneto/medvita-core/issues/31)) — PR [#59](https://github.com/alaorneto/medvita-core/pull/59)
- Adicionar modelos e documentos clínicos simples ([#32](https://github.com/alaorneto/medvita-core/issues/32)) — PR [#59](https://github.com/alaorneto/medvita-core/pull/59)
- Adicionar anexos, trilha de leitura e integração com a página do paciente ([#33](https://github.com/alaorneto/medvita-core/issues/33)) — PR [#59](https://github.com/alaorneto/medvita-core/pull/59)
- Criar as páginas do prontuário e a API REST e fechar a documentação de `med_records` ([#34](https://github.com/alaorneto/medvita-core/issues/34)) — PR [#59](https://github.com/alaorneto/medvita-core/pull/59)
- Criar tabela de preços, caixa e o `setup` com o livro contábil ([#36](https://github.com/alaorneto/medvita-core/issues/36)) — PR [#59](https://github.com/alaorneto/medvita-core/pull/59)
- Implementar a sessão de caixa com suprimento e sangria ([#37](https://github.com/alaorneto/medvita-core/issues/37)) — PR [#59](https://github.com/alaorneto/medvita-core/pull/59)
- Implementar a conta do paciente com título no livro ([#38](https://github.com/alaorneto/medvita-core/issues/38)) — PR [#59](https://github.com/alaorneto/medvita-core/pull/59)
- Registrar pagamentos com baixa no livro e estorno ([#39](https://github.com/alaorneto/medvita-core/issues/39)) — PR [#59](https://github.com/alaorneto/medvita-core/pull/59)
- Emitir recibos numerados, selados e anuláveis ([#40](https://github.com/alaorneto/medvita-core/issues/40)) — PR [#59](https://github.com/alaorneto/medvita-core/pull/59)
- Integrar o financeiro com a agenda e com a página do paciente ([#41](https://github.com/alaorneto/medvita-core/issues/41)) — PR [#59](https://github.com/alaorneto/medvita-core/pull/59)
- Criar as páginas do financeiro e a API REST ([#42](https://github.com/alaorneto/medvita-core/issues/42)) — PR [#59](https://github.com/alaorneto/medvita-core/pull/59)
- Adicionar relatórios e fechar a documentação de `med_finance` ([#43](https://github.com/alaorneto/medvita-core/issues/43)) — PR [#59](https://github.com/alaorneto/medvita-core/pull/59)
- Criar a lista de configuração da clínica, o guia de implantação e os dados de demonstração ([#47](https://github.com/alaorneto/medvita-core/issues/47)) — PR [#59](https://github.com/alaorneto/medvita-core/pull/59)
- Ligar as apps aos planos com medidores de quota ([#48](https://github.com/alaorneto/medvita-core/issues/48)) — PR [#59](https://github.com/alaorneto/medvita-core/pull/59)
- Aceitar tokens de cliente nativo nas APIs dos apps ([#61](https://github.com/alaorneto/medvita-core/issues/61)) — PR [#68](https://github.com/alaorneto/medvita-core/pull/68)
- Entregar o tema da marca Medvita como tema da instância trazido pela suíte ([#65](https://github.com/alaorneto/medvita-core/issues/65)) — PR [#69](https://github.com/alaorneto/medvita-core/pull/69)
- Dar forma de pagamento ao tipo, escolher os tipos de cada agenda e sugerir a duração ao marcar ([#79](https://github.com/alaorneto/medvita-core/issues/79)) — PR [#92](https://github.com/alaorneto/medvita-core/pull/92)
- Criar a agenda junto com o profissional e listar os calendários na agenda médica ([#85](https://github.com/alaorneto/medvita-core/issues/85)) — PR [#94](https://github.com/alaorneto/medvita-core/pull/94)
- Mostrar o link de assinatura de cada agenda e os calendários compartilhados ([#87](https://github.com/alaorneto/medvita-core/issues/87)) — PR [#94](https://github.com/alaorneto/medvita-core/pull/94)

### Melhorias

- Editar a grade semanal com vários períodos por dia e tipos por período ([#80](https://github.com/alaorneto/medvita-core/issues/80)) — PR [#92](https://github.com/alaorneto/medvita-core/pull/92)

### Correções

- Descontar as consultas ativas dos horários livres e mostrar períodos restritos a um tipo ([#76](https://github.com/alaorneto/medvita-core/issues/76)) — PR [#92](https://github.com/alaorneto/medvita-core/pull/92)
- Manter o encaixe ao remarcar para outra agenda e travar a agenda antes da consulta ([#77](https://github.com/alaorneto/medvita-core/issues/77)) — PR [#92](https://github.com/alaorneto/medvita-core/pull/92)
- Mostrar a cor do tipo de atendimento nas listas de consultas ([#78](https://github.com/alaorneto/medvita-core/issues/78)) — PR [#92](https://github.com/alaorneto/medvita-core/pull/92)

### Documentação

- Escrever o `AGENTS.md` da raiz e das apps e a documentação de arquitetura ([#5](https://github.com/alaorneto/medvita-core/issues/5)) — PR [#50](https://github.com/alaorneto/medvita-core/pull/50)
- Corrigir em docs/architecture.md como a conta do financeiro nasce ([#88](https://github.com/alaorneto/medvita-core/issues/88)) — PR [#91](https://github.com/alaorneto/medvita-core/pull/91)

### Manutenção

- Criar o repositório com licença proprietária e o fluxo `dev-workflow` ([#2](https://github.com/alaorneto/medvita-core/issues/2)) — PR [#50](https://github.com/alaorneto/medvita-core/pull/50)
- Rodar lint, suíte em PostgreSQL com a role runtime e diagnóstico dos pacotes no CI ([#4](https://github.com/alaorneto/medvita-core/issues/4)) — PR [#50](https://github.com/alaorneto/medvita-core/pull/50)
- Criar as fixtures compartilhadas da clínica A/B ([#6](https://github.com/alaorneto/medvita-core/issues/6)) — PR [#50](https://github.com/alaorneto/medvita-core/pull/50)
- Provar a jornada completa da clínica e as matrizes de isolamento ([#45](https://github.com/alaorneto/medvita-core/issues/45)) — PR [#59](https://github.com/alaorneto/medvita-core/pull/59)
- Provar os pontos de extensão com a app de referência `med_example` ([#46](https://github.com/alaorneto/medvita-core/issues/46)) — PR [#59](https://github.com/alaorneto/medvita-core/pull/59)
- Fechar as issues de PRs mesclados em branches empilhadas ([#58](https://github.com/alaorneto/medvita-core/issues/58)) — PR [#60](https://github.com/alaorneto/medvita-core/pull/60)
- Atualizar o skill dev-workflow para 1.2.1 ([#62](https://github.com/alaorneto/medvita-core/issues/62)) — PR [#63](https://github.com/alaorneto/medvita-core/pull/63)
- Atualizar o SKELETON_REF para o núcleo com a aparência da instância ([#64](https://github.com/alaorneto/medvita-core/issues/64)) — PR [#67](https://github.com/alaorneto/medvita-core/pull/67)
- Trocar os identificadores das apps de io.katua.sk.med para io.medvita ([#70](https://github.com/alaorneto/medvita-core/issues/70)) — PR [#72](https://github.com/alaorneto/medvita-core/pull/72)
- Renomear a suíte e o repositório de sk_med_core para medvita-core ([#71](https://github.com/alaorneto/medvita-core/issues/71)) — PR [#89](https://github.com/alaorneto/medvita-core/pull/89)
- Subir o núcleo para a versão com link de assinatura por calendário ([#86](https://github.com/alaorneto/medvita-core/issues/86)) — PR [#94](https://github.com/alaorneto/medvita-core/pull/94)
- bootstrap repository, license and dev workflow ([475211d](https://github.com/alaorneto/medvita-core/commit/475211d0807af05f1d058e16611cbac173aa41b5)) — parte de [#2](https://github.com/alaorneto/medvita-core/issues/2)
- **deps:** bump anthropics/claude-code-action from 1.0.275 to 1.0.276 (PR [#57](https://github.com/alaorneto/medvita-core/pull/57))
