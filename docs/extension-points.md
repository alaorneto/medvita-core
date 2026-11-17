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
| `med_scheduling.appointment_booked`, `_rescheduled`, `_confirmed`, `_arrived`, `_started`, `_completed`, `_no_show`, `_cancelled` | `med_scheduling.appointment` | `code`, `schedule`, `patient`, `appointment_type`, `billing_code`, `starts_at`, `ends_at`, `status` |
| `med_records.encounter_signed` | `med_records.encounter` | `code`, `chart`, `patient`, `kind`, `occurred_at`, `seal_digest` |
| `med_records.document_issued` | `med_records.clinicaldocument` | `code`, `chart`, `patient`, `kind`, `seal_digest` |
| `med_finance.charge_confirmed`, `charge_paid`, `charge_cancelled` | `med_finance.charge` | `code`, `desk`, `patient`, `status`, `total`, `origin_app`, `origin_key` |
| `med_finance.payment_registered`, `payment_reversed` | `med_finance.payment` | `charge`, `method`, `amount`, `status` |
| `med_finance.receipt_issued`, `receipt_voided` | `med_finance.receipt` | `number`, `charge`, `amount`, `seal_digest` |

Toda chave de payload é um campo do modelo declarado em `read_fields` e em `payload_fields` do tipo, nunca em `personal_fields` nem em `sensitive_fields`. FK sai como o `sysid` em texto.

## 3. Registries de interface e de regra

Funções exportadas pelo `service_api` da app dona, chamadas no `ready()` da app que se pluga. Todas recusam (`ValueError`) código duplicado ou fora do formato `<app_label>.<nome>`, e só mostram a contribuição de uma app ativa na organização.

| App dona | Função | Para quê |
|---|---|---|
| `med_patients` | `register_patient_section(PatientSection(code, label, url_name, order, visible))` | Aba ou atalho na página do paciente; `visible(actor=..., patient_id=...)`, opcional, esconde a aba de quem só veria uma página vazia |
| `med_patients` | `register_timeline_provider(code, provider)` | Itens na linha do tempo do paciente: `provider(*, actor, patient_id, before, limit)` autoriza e devolve até `limit` `TimelineEntry` com `at <= before` |
| `med_patients` | `register_consent_purpose(ConsentPurpose(code, label, description))` | Finalidade de consentimento LGPD |
| `med_patients` | `register_retention_guard(code, guard)` | Veto à anonimização ou exclusão de paciente; `guard(patient_id=...)` devolve o motivo ou `None` |
| `med_patients` | `register_patient_data_provider(code, provider)` | Seção do relatório "dados do titular" |
| `med_patients` | `register_setup_step(SetupStep(code, label, url_name, is_done, order))` | Passo da lista "Configuração da clínica" |
| `med_scheduling` | `register_appointment_action(AppointmentAction(code, label, url_name, statuses, order))` | Botão numa consulta ("Atender", "Receber") |
| `med_records` | `register_section_type(SectionType(code, label, fields, version, has_text))` | Tipo de seção estruturada do atendimento; `fields` são `SectionField(name, label, kind, required, unit, min, max, choices)` com `kind` em `text`, `long_text`, `integer`, `decimal`, `boolean`, `choice`, `date`, `icd10_list`. Uma `version` nova convive com as antigas: o formulário usa a maior, a seção gravada guarda a dela |
| `med_records` | `register_document_kind(DocumentKind(code, label, default_body, notice))` | Tipo de documento clínico; o texto padrão aceita só os marcadores `{{patient_name}}`, `{{date}}` e `{{professional_name}}`, trocados literalmente |
| `med_finance` | `register_charge_origin(ChargeOrigin(app_label, label))` | App que cria contas por `FinanceService.create_charge(origin_app=..., origin_key=...)`; a mesma origem devolve a mesma conta |

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

A app de referência executável está em [`tests/apps/med_example/`](../tests/apps/med_example/): ela usa **todos** os pontos de extensão (aba com `visible` opcional, linha do tempo, finalidade de consentimento, guarda de retenção, relatório do titular, passo de configuração, ação de consulta, tipo de seção, tipo de documento, origem de conta, consumidores de `appointment_completed` e `encounter_signed`, verificação do selo) sem alterar nenhuma das quatro apps, e os testes dela (`tests/apps/med_example/tests/`) provam cada um com a app ativa e desativada. Ela entra em `SKELETON_DEV_APPS` nos testes e nunca é empacotada.

### Como criar um add-on

1. Crie a app no repositório dela, com `skeleton_startapp`, e declare em `dependencies` do manifesto as apps da suíte que ela usa, com a faixa da versão corrente.
2. Importe das apps da suíte só o `service_api` (o check E019 recusa o resto) e do núcleo só as superfícies públicas.
3. No `ready()`, chame os `register_*` que precisar, com códigos `<sua_app>.<nome>`; contribuições só aparecem com a app ativa na organização.
4. Consumidores de evento rodam em contexto de sistema e precisam ser idempotentes; não há como numerar nem chamar serviços de ator nesse contexto (alaorneto/skeleton#577).
5. Teste com a fixture `clinic` e os serviços públicos, como `tests/apps/med_example/tests/test_extension_points.py`.
