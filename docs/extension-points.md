# Pontos de extensão

Uma app futura (laudos, lembretes, portal, um pacote de especialidade) se pluga sem alterar as quatro apps, por quatro mecanismos. Ela declara as apps de que depende em `dependencies` do manifesto e importa só o `service_api` delas.

## 1. API de serviços

`PatientService`, `SchedulingService`, `RecordsService` e `FinanceService`, com o contrato do núcleo: métodos keyword-only com `actor`, DTO congelado, `expected_revision` nas alterações e `idempotency_key` nas criações repetíveis. A referência de cada uma está em `docs/service-api.md` do pacote.

## 2. Eventos de domínio do núcleo

As apps publicam pelo `EventService` do núcleo; quem consome registra `register_consumer("<tipo>", "<app>.<nome>", handler)` no `ready()`.

| Tipo | Tabela | Payload |
|---|---|---|
| `med_patients.patient_created`, `patient_updated`, `patient_status_changed` | `med_patients.patient` | `code`, `status`, `registry` |
| `med_patients.consent_changed` | `med_patients.consent` | `patient`, `purpose`, `status` |
| `med_scheduling.appointment_booked`, `_rescheduled`, `_confirmed`, `_arrived`, `_started`, `_completed`, `_no_show`, `_cancelled`, `_modality_changed` | `med_scheduling.appointment` | `code`, `schedule`, `patient`, `appointment_type`, `billing_code`, `starts_at`, `ends_at`, `status`, `mode`, `modality` |
| `med_records.encounter_signed` | `med_records.encounter` | `code`, `chart`, `patient`, `kind`, `occurred_at`, `seal_digest` |
| `med_records.document_issued` | `med_records.clinicaldocument` | `code`, `chart`, `patient`, `kind`, `seal_digest` |
| `med_records.items_consumed` | `med_records.encounterconsumption` | `encounter`, `provider`, `item_ref`, `quantity`, `lot` |
| `med_finance.charge_confirmed`, `charge_paid`, `charge_cancelled` | `med_finance.charge` | `code`, `desk`, `patient`, `status`, `total`, `origin_app`, `origin_key` |
| `med_finance.payment_registered`, `payment_reversed` | `med_finance.payment` | `charge`, `method`, `amount`, `status` |
| `med_finance.receipt_issued`, `receipt_voided` | `med_finance.receipt` | `number`, `charge`, `amount`, `seal_digest` |

Os eventos do financeiro não levam pagador, documento nem descrição. Uma app que emite documento fiscal (Receita Saúde, NFS-e) parte de `payment_registered` e lê o resto por `FinanceService().fiscal_data(actor=..., payment_id=...)`, autorizado pela leitura do caixa. O método exige um ator: o consumidor do evento, que roda sem ator, registra o pendente na própria app, e a leitura acontece numa ação de quem lê o caixa.

Toda chave de payload é um campo do modelo declarado em `read_fields` e em `payload_fields` do tipo, nunca em `personal_fields` nem em `sensitive_fields`. FK sai como o `sysid` em texto.

`mode` da consulta é `booked` (hora marcada) ou `walk_in` (ordem de chegada). Na ordem de chegada a consulta não tem hora: `starts_at` e `ends_at` são os limites do período em que o paciente é atendido. O consumidor que mostra ou agenda algo pela hora da consulta olha `mode` antes.

`modality` é `in_person` (presencial) ou `telehealth` (teleconsulta): a consulta copia a do tipo na marcação e a troca até o início, com o evento `appointment_modality_changed`. Uma app de telemedicina abre a sala pelos eventos de uma consulta `telehealth` e a fecha quando a consulta é cancelada ou volta a ser presencial.

## 3. Registries de interface e de regra

Funções exportadas pelo `service_api` da app dona, chamadas no `ready()` da app que se pluga. Todas recusam (`ValueError`) código duplicado ou fora do formato `<app_label>.<nome>`, e só mostram a contribuição de uma app ativa na organização.

| App dona | Função | Para quê |
|---|---|---|
| `med_patients` | `register_patient_section(PatientSection(code, label, url_name, order, visible, icon))` | Aba ou atalho na página do paciente; `visible(actor=..., patient_id=...)`, opcional, esconde a aba de quem só veria uma página vazia. As abas vão por uso: Resumo (0), as seções por `order` (Consultas 20, Prontuário 30, Financeiro 40), depois as próprias do cadastro (Cadastro 50, Linha do tempo 54, Privacidade 55; Responsáveis, Convênios e Consentimentos são subabas de Cadastro, #149); uma seção acima de 55 vem depois delas. A faixa quebra linha no desktop, então uma aba a mais não esconde as outras |
| `med_patients` | `register_summary_panel(SummaryPanel(code, label, template, order, visible, context, icon))` | Painel da aba Resumo, a primeira da página do paciente: o template é renderizado com `panel`, `organization_id`, `patient_id` e o que `context(actor=..., patient_id=...)` devolve (um mapeamento de nomes, lido pelo serviço da própria app com o acesso do ator); `visible(actor=..., patient_id=...)`, opcional, esconde o painel de quem nada leria nele. Um `visible`, `context` ou template que falha esconde só aquele painel. Os da suíte: próxima e última consulta com "Marcar consulta" (agenda, 10), alergias e medicamentos em uso só para quem lê um arquivo clínico (prontuário, 20), saldo em aberto com "Nova conta" (financeiro, 30) e o convênio principal com a validade (pacientes, 40) |
| `med_patients` | `register_timeline_provider(code, provider)` | Itens na linha do tempo do paciente: `provider(*, actor, patient_id, before, limit)` autoriza e devolve até `limit` `TimelineEntry` com `at <= before` |
| `med_patients` | `register_consent_purpose(ConsentPurpose(code, label, description))` | Finalidade de consentimento LGPD |
| `med_patients` | `register_retention_guard(code, guard)` | Veto à anonimização ou exclusão de paciente; `guard(patient_id=...)` devolve o motivo ou `None` |
| `med_patients` | `register_patient_data_provider(code, provider)` | Seção do relatório "dados do titular" |
| `med_patients` | `register_setup_step(SetupStep(code, label, url_name, is_done, order))` | Passo da lista "Configuração da clínica" |
| `med_patients` | `register_portal_patients(code, resolver)` | Os pacientes por quem a pessoa externa do portal age: `resolver(*, actor, access_id)` roda no portal e devolve os `sysid` que a app ligou àquele acesso; só os resolvers da app que admitiu a pessoa são consultados. A agenda marca pelo portal só para esses pacientes (`SchedulingService.book_external`) |
| `med_scheduling` | `register_appointment_action(AppointmentAction(code, label, url_name, statuses, order, icon))` | Botão numa consulta ("Atender", "Receber"); `icon`, opcional, é o conceito cujo ícone o botão mostra |
| `med_records` | `register_section_type(SectionType(code, label, fields, version, has_text))` | Tipo de seção estruturada do atendimento; `fields` são `SectionField(name, label, kind, required, unit, min, max, choices)` com `kind` em `text`, `long_text`, `integer`, `decimal`, `boolean`, `choice`, `date`, `icd10_list`. Uma `version` nova convive com as antigas: o formulário usa a maior, a seção gravada guarda a dela |
| `med_records` | `register_document_kind(DocumentKind(code, label, default_body, notice))` | Tipo de documento clínico; o texto padrão aceita só os marcadores `{{patient_name}}`, `{{date}}` e `{{professional_name}}`, trocados literalmente. O código registrado é o `kind` que `document_issued` publica |
| `med_records` | `register_encounter_panel(EncounterPanel(code, label, template, url_name, order, visible, context))`, `register_document_panel(DocumentPanel(...))` | Painel na página do atendimento assinado e na do documento emitido (assinatura ICP-Brasil, prescrição): um template renderizado com o `sysid` e os pares em texto que `context(actor=..., encounter_id=...)` devolve, ou um link; só para quem lê o arquivo, nunca com conteúdo clínico |
| `med_records` | `register_consumable_provider(code, provider)` | Itens que o atendimento registra como consumidos (estoque, vacinas): `provider(*, actor)` devolve os `ConsumableItem(ref, label, unit)` que o ator pode escolher; o atendimento guarda a fotografia, a assinatura sela e publica `items_consumed` com a referência, sem a descrição nem o paciente |
| `med_finance` | `register_charge_origin(ChargeOrigin(app_label, label))` | App que cria contas por `FinanceService.create_charge(origin_app=..., origin_key=...)`; a mesma origem devolve a mesma conta |
| `med_finance` | `register_charge_panel(ChargePanel(code, label, template, url_name, order, visible, context))`, `register_receipt_panel(ReceiptPanel(...))` | Painel na página da conta e na do recibo, depois do conteúdo do financeiro: um template renderizado com o `sysid` e os pares em texto que `context(actor=..., charge_id=...)` devolve, ou um link (`url_name` recebe `org` e o `sysid`); só para quem lê o caixa |

Um pacote de especialidade registra os próprios tipos de seção (por exemplo, `<app>.ophthalmic_exam` com acuidade visual e pressão intraocular) e de documento; o prontuário os valida e mostra como os básicos, sem mudar nada em `med_records`.

## 4. Selo como base de assinatura

`Encounter`, `ClinicalDocument` e `Receipt` são selados pelo núcleo; o `seal_digest` sai nos eventos. Uma app de assinatura digital assina esse resumo e o confere com `RecordSealService().verify(...)`, sem tocar nas tabelas das quatro apps.

## Exemplo: uma app que usa os quatro mecanismos

```python
# med_example/apps.py
class MedExampleConfig(AppConfig):
    name = __package__
    label = "med_example"

    def ready(self):
        from skeleton.events.registry import register_consumer

        from applications.med_patients.service_api import PatientSection, register_patient_section
        from applications.med_records.service_api import SectionType, SectionField, register_section_type

        from .handlers import note_signed_encounter

        register_patient_section(PatientSection("med_example.notes", _("Notas"), "med_example:notes", order=90))
        register_section_type(
            SectionType("med_example.scale", _("Escala"), (SectionField("score", _("Pontos"), "integer"),), 1)
        )
        register_consumer("med_records.encounter_signed", "med_example.note_signed", note_signed_encounter)
```

A app de referência executável está em [`tests/apps/med_example/`](../tests/apps/med_example/): ela usa **todos** os pontos de extensão (aba com `visible` opcional, painel do resumo, linha do tempo, finalidade de consentimento, guarda de retenção, relatório do titular, passo de configuração, ação de consulta, tipo de seção, tipo de documento, painéis do atendimento e do documento, provedor de itens consumidos, origem de conta, painéis da conta e do recibo, consumidores de `appointment_completed` e `encounter_signed`, verificação do selo) sem alterar nenhuma das quatro apps, e os testes dela (`tests/apps/med_example/tests/`) provam cada um com a app ativa e desativada. Ela entra em `SKELETON_DEV_APPS` nos testes e nunca é empacotada.

### Como criar um add-on

1. Crie a app no repositório dela, com `skeleton_startapp`, e declare em `dependencies` do manifesto as apps da suíte que ela usa, com a faixa da versão corrente.
2. Importe das apps da suíte só o `service_api` (o check E019 recusa o resto) e do núcleo só as superfícies públicas.
3. No `ready()`, chame os `register_*` que precisar, com códigos `<sua_app>.<nome>`; contribuições só aparecem com a app ativa na organização.
4. Consumidores de evento rodam em contexto de sistema e precisam ser idempotentes; não há como numerar nem chamar serviços de ator nesse contexto (alaorneto/skeleton#577).
5. Teste com a fixture `clinic` e os serviços públicos, como `tests/apps/med_example/tests/test_extension_points.py`.
