"""Pages of the records app: every read and write goes through RecordsService (and the other apps' services).

Clinical pages answer ``Cache-Control: no-store`` (``never_cache``), show clinical text escaped
(line breaks by CSS, never ``|safe``) and never put the patient's name in the page title, a URL
or a flash message. A chart, encounter or document the actor cannot read answers 404.
"""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any
from uuid import UUID

from django.contrib import messages
from django.db import transaction
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.utils.translation import gettext
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_POST

from applications.med_patients.service_api import PatientService
from skeleton.service_api import Conflict, Forbidden, InvalidInput, NotFound
from skeleton.web.views import tenant_page

from . import forms as record_forms
from .extension import SECTION_TYPES, active_document_kinds, active_section_types
from .sections import body_mass_index
from .service_api import ConsumptionInput, RecordsService, TemplateSectionInput

logger = logging.getLogger(__name__)


def _service() -> RecordsService:
    return RecordsService()


def conflict_text(error: Conflict) -> str:
    texts = {
        "stale_revision": gettext("O registro mudou desde que a página abriu. Atualize a página e tente de novo."),
        "signed": gettext("O atendimento já foi assinado e não muda; use um adendo."),
        "issued": gettext("O documento já foi emitido e não muda; substitua-o."),
        "empty": gettext("Preencha ao menos uma seção antes de assinar."),
        "professional_required": gettext("Só um profissional com conselho cadastrado na agenda assina."),
        "not_signed": gettext("Só um atendimento assinado recebe adendo."),
        "not_issued": gettext("Só um documento emitido é substituído."),
        "already_set_up": gettext("O prontuário já foi configurado nesta organização."),
    }
    return texts.get(error.code, gettext("A operação conflita com o estado atual."))


def _errors(error: InvalidInput) -> str:
    return " ".join(text for texts in error.errors.values() for text in texts)


def _revision(request: HttpRequest) -> int:
    try:
        return int(request.POST.get("revision", ""))
    except ValueError:
        return 0


def _key(request: HttpRequest) -> str:
    return (request.POST.get("idempotency_key") or "")[:150] or uuid.uuid4().hex


def _uuid(value: Any) -> UUID:
    try:
        return UUID(str(value))
    except (TypeError, ValueError):
        raise Http404 from None


def _patient(request: HttpRequest, patient_id: UUID) -> Any:
    try:
        return PatientService().summary(actor=request.user, patient_id=patient_id)
    except (NotFound, Forbidden):
        return None


def _rendered_panels(request: HttpRequest, organization_id: UUID, panels: Any, **target: UUID) -> list[dict[str, Any]]:
    """The panels of other apps, rendered: a template inline or a link. A template that fails is left out."""
    from django.template.loader import render_to_string
    from django.urls import NoReverseMatch, reverse

    shown = []
    for panel in panels:
        if panel.url_name:
            try:
                url = reverse(panel.url_name, args=(organization_id, *target.values()))
            except NoReverseMatch:
                continue
            shown.append({"code": panel.code, "label": panel.label, "url": url, "html": ""})
            continue
        values = {**dict(panel.context), "panel": panel, "organization_id": organization_id, **target}
        try:
            html = render_to_string(panel.template, values, request=request)
        except Exception as exc:  # noqa: BLE001 - one app's panel never breaks a clinical page
            logger.warning("med_records.panel_failed", extra={"contribution": panel.code, "error": type(exc).__name__})
            continue
        shown.append({"code": panel.code, "label": panel.label, "url": "", "html": html})
    return shown


def _context(organization_id: UUID, **values: Any) -> dict[str, Any]:
    return {"organization_id": organization_id, **values}


def _section_rows(section: Any) -> list[dict[str, Any]]:
    """Label and value of each structured field of a stored section, by the version it was saved with."""
    kind = SECTION_TYPES.get(section.section_type, section.type_version)
    data = json.loads(section.data_json)
    rows = []
    for field in kind.fields if kind else ():
        if field.name not in data:
            continue
        value = data[field.name]
        if field.kind == "icd10_list":
            value = "; ".join(
                f"{item['code']} {item['description']}".strip()
                + (" (" + gettext("principal") + ")" if item["primary"] else "")
                for item in value
            )
        elif field.kind == "boolean":
            value = gettext("Sim") if value else gettext("Não")
        elif field.kind == "choice":
            value = str(dict(field.choices).get(value, value))
        elif field.unit:
            value = f"{value} {field.unit}"
        rows.append({"label": field.label, "value": value})
    if section.section_type == "med_records.vitals" and body_mass_index(data):
        rows.append({"label": gettext("IMC (calculado)"), "value": body_mass_index(data)})
    return rows


def _sections(info: Any) -> list[dict[str, Any]]:
    result = []
    for section in info.sections:
        kind = SECTION_TYPES.get(section.section_type, section.type_version)
        result.append(
            {"section": section, "label": kind.label if kind else section.section_type, "rows": _section_rows(section)}
        )
    return result


# ------------------------------------------------------------------------------------ home and setup


@tenant_page()
def home(request: HttpRequest, organization_id: UUID) -> HttpResponse:
    from skeleton.service_api.access import AccessService

    archives = _service().archives(actor=request.user)
    manager = "access.manage" in AccessService().capabilities(actor=request.user)
    return render(request, "med_records/home.html", _context(organization_id, archives=archives, manager=manager))


@tenant_page()
def setup_view(request: HttpRequest, organization_id: UUID) -> HttpResponse:
    from skeleton.service_api.access import AccessService
    from skeleton.service_api.organizations import OrganizationService

    if "access.manage" not in AccessService().capabilities(actor=request.user):
        raise Http404
    groups = OrganizationService().groups(actor=request.user, page_size=100).items
    form = record_forms.SetupForm(request.POST or None, groups=groups)
    status = 200
    if request.method == "POST":
        status = 400
        if form.is_valid():
            values = form.cleaned_data
            try:
                with transaction.atomic():
                    _service().setup(
                        actor=request.user,
                        mode=values["mode"],
                        name=values["name"],
                        member_group_ids=tuple(UUID(value) for value in values["member_groups"]),
                        idempotency_key=f"page-setup-{organization_id}",
                    )
            except (NotFound, Forbidden):
                raise Http404 from None
            except InvalidInput as error:
                record_forms.apply_service_errors(form, error)
            except Conflict as error:
                form.add_error(None, conflict_text(error))
            else:
                messages.success(request, gettext("Prontuário configurado."))
                return redirect("med_records:home", organization_id)
    return render(request, "med_records/setup.html", _context(organization_id, form=form), status=status)


# ------------------------------------------------------------------------------------ patient tab


@never_cache
@tenant_page()
def patient_section(request: HttpRequest, organization_id: UUID, patient_id: UUID) -> HttpResponse:
    """The "Prontuário" tab of the patient page: the chart of the chosen archive."""
    from django.urls import NoReverseMatch, reverse

    patient = _patient(request, patient_id)
    archives = _service().archives(actor=request.user)
    if patient is None or not archives:
        raise Http404
    tabs = []
    for tab in PatientService().page_tabs(actor=request.user, patient_id=patient_id):
        try:
            url = reverse(tab.url_name, args=(organization_id, patient_id))
        except NoReverseMatch:
            continue
        tabs.append({"label": tab.label, "url": url, "current": tab.code == "med_records.chart"})
    chosen = request.GET.get("archive")
    archive = next((item for item in archives if str(item.sysid) == chosen), archives[0])
    charts = {
        chart.archive_id: chart for chart in _service().charts_for_patient(actor=request.user, patient_id=patient_id)
    }
    chart = charts.get(archive.sysid)
    context = _context(organization_id, patient=patient, tabs=tabs, archives=archives, archive=archive, chart=chart)
    if chart is not None:
        context.update(
            summary=_service().chart_summary(actor=request.user, chart_id=chart.sysid),
            encounters=_service().encounters(actor=request.user, chart_id=chart.sysid, page_size=50).items,
            documents=_service().documents(actor=request.user, chart_id=chart.sysid),
            attachments=_service().attachments(actor=request.user, chart_id=chart.sysid),
            encounter_form=record_forms.NewEncounterForm(
                templates=_service().templates(actor=request.user, archive_id=archive.sysid, kind="encounter")
            ),
            document_form=record_forms.NewDocumentForm(
                kinds=active_document_kinds(request.user),
                templates=_service().templates(actor=request.user, archive_id=archive.sysid, kind="document"),
            ),
            idempotency_key=uuid.uuid4().hex,
        )
    return render(request, "med_records/patient_section.html", context)


@require_POST
@tenant_page()
def chart_open(request: HttpRequest, organization_id: UUID, patient_id: UUID) -> HttpResponse:
    archive_id = request.POST.get("archive") or ""
    try:
        with transaction.atomic():
            chart = _service().open_chart(
                actor=request.user, patient_id=patient_id, archive_id=_uuid(archive_id) if archive_id else None
            )
    except (NotFound, Forbidden):
        raise Http404 from None
    except InvalidInput:
        messages.error(request, gettext("Escolha o arquivo clínico."))
        return redirect("med_records:patient_section", organization_id, patient_id)
    response = redirect("med_records:patient_section", organization_id, patient_id)
    response["Location"] += f"?archive={chart.archive_id}"
    return response


@require_POST
@tenant_page()
def chart_attach(request: HttpRequest, organization_id: UUID, chart_id: UUID) -> HttpResponse:
    upload = request.FILES.get("file")
    try:
        chart = _service().chart(actor=request.user, chart_id=chart_id)
        if upload is None:
            raise InvalidInput({"file": [gettext("Escolha um arquivo.")]})
        with transaction.atomic():
            _service().attach_to_chart(
                actor=request.user, chart_id=chart_id, filename="exame", stream=upload, content_type=upload.content_type
            )
    except (NotFound, Forbidden):
        raise Http404 from None
    except InvalidInput as error:
        messages.error(request, _errors(error))
    else:
        messages.success(request, gettext("Anexo incluído."))
    response = redirect("med_records:patient_section", organization_id, chart.patient_id)
    response["Location"] += f"?archive={chart.archive_id}"
    return response


@never_cache
@tenant_page()
def attachment_download(request: HttpRequest, organization_id: UUID, attachment_id: UUID) -> HttpResponse:
    """Redirect to the core's authorized download of an attachment of a chart or encounter (trail recorded)."""
    target = {}
    if request.GET.get("chart"):
        target["chart_id"] = _uuid(request.GET["chart"])
    elif request.GET.get("encounter"):
        target["encounter_id"] = _uuid(request.GET["encounter"])
    else:
        raise Http404
    try:
        url = _service().attachment_url(actor=request.user, attachment_id=attachment_id, **target)
    except (NotFound, Forbidden, InvalidInput):
        raise Http404 from None
    return redirect(url)


@require_POST
@tenant_page()
def encounter_new(request: HttpRequest, organization_id: UUID, chart_id: UUID) -> HttpResponse:
    form = record_forms.NewEncounterForm(
        request.POST, templates=_service().templates(actor=request.user, kind="encounter")
    )
    if not form.is_valid():
        raise Http404
    template = form.cleaned_data["template"]
    try:
        with transaction.atomic():
            info = _service().start_encounter(
                actor=request.user,
                chart_id=chart_id,
                kind=form.cleaned_data["kind"],
                template_id=_uuid(template) if template else None,
                idempotency_key=_key(request),
            )
    except (NotFound, Forbidden):
        raise Http404 from None
    return redirect("med_records:encounter_edit", organization_id, info.header.sysid)


@never_cache
@tenant_page()
def attend(request: HttpRequest, organization_id: UUID, appointment_id: UUID) -> HttpResponse:
    """From an appointment: open (or resume) the actor's draft encounter of that appointment."""
    from applications.med_scheduling.service_api import SchedulingService

    try:
        appointment = SchedulingService().appointment(actor=request.user, appointment_id=appointment_id).appointment
        with transaction.atomic():
            chart = _service().open_chart(actor=request.user, patient_id=appointment.patient_id)
            info = _service().start_encounter(
                actor=request.user,
                chart_id=chart.sysid,
                appointment_id=appointment.sysid,
                idempotency_key=f"attend-{appointment.sysid}",
            )
    except (NotFound, Forbidden, InvalidInput):
        raise Http404 from None
    if info.header.signed:
        return redirect("med_records:encounter", organization_id, info.header.sysid)
    return redirect("med_records:encounter_edit", organization_id, info.header.sysid)


# ------------------------------------------------------------------------------------ encounters


def _encounter_context(request: HttpRequest, organization_id: UUID, encounter_id: UUID) -> dict[str, Any]:
    try:
        info = _service().encounter(actor=request.user, encounter_id=encounter_id)
        attachments = _service().attachments(actor=request.user, encounter_id=encounter_id)
    except (NotFound, Forbidden):
        raise Http404 from None
    return _context(
        organization_id,
        info=info,
        header=info.header,
        sections=_sections(info),
        attachments=attachments,
        patient=_patient(request, info.header.patient_id),
    )


@never_cache
@tenant_page()
def encounter_view(request: HttpRequest, organization_id: UUID, encounter_id: UUID) -> HttpResponse:
    context = _encounter_context(request, organization_id, encounter_id)
    try:
        panels = _service().encounter_panels(actor=request.user, encounter_id=encounter_id)
    except (NotFound, Forbidden):
        raise Http404 from None
    context.update(
        addendum_form=record_forms.AddendumForm(),
        idempotency_key=uuid.uuid4().hex,
        panels=_rendered_panels(request, organization_id, panels, encounter_id=context["header"].sysid),
    )
    return render(request, "med_records/encounter.html", context)


@never_cache
@tenant_page()
def encounter_print(request: HttpRequest, organization_id: UUID, encounter_id: UUID) -> HttpResponse:
    from applications.med_scheduling.service_api import SchedulingService

    context = _encounter_context(request, organization_id, encounter_id)
    try:
        context["practice"] = SchedulingService().practice(actor=request.user)
    except (NotFound, Forbidden):
        context["practice"] = None
    return render(request, "med_records/encounter_print.html", context)


def _encounter_post(request: HttpRequest, organization_id: UUID, encounter_id: UUID, info: Any, types: dict) -> Any:
    """Run one action of the draft editor; return a response to send, or ``None`` to render again."""
    action = request.POST.get("action", "")
    if action == "section":
        kind = types.get(request.POST.get("section_type", ""))
        if kind is None:
            raise Http404
        form = record_forms.section_form(kind, request.POST, prefix="s")
        if not form.is_valid():
            raise InvalidInput({"data": [gettext("Confira os campos da seção.")]})
        try:
            position = int(request.POST.get("position", "0"))
        except ValueError:
            position = 0
        _service().save_section(
            actor=request.user,
            encounter_id=encounter_id,
            section_type=kind.code,
            data=record_forms.section_data(kind, form.cleaned_data),
            text=form.cleaned_data.get("text", "") or "",
            position=position,
            expected_revision=_revision(request),
        )
        messages.success(request, gettext("Seção salva."))
    elif action == "consumption_add":
        provider, _sep, ref = request.POST.get("item", "").partition("|")
        _service().add_consumption(
            actor=request.user,
            encounter_id=encounter_id,
            item=ConsumptionInput(
                provider=provider,
                item_ref=ref,
                quantity=(request.POST.get("quantity") or "").strip()[:20],
                lot=(request.POST.get("lot") or "")[:41],
            ),
            expected_revision=_revision(request),
        )
        messages.success(request, gettext("Item consumido incluído."))
    elif action == "consumption_remove":
        _service().remove_consumption(
            actor=request.user,
            encounter_id=encounter_id,
            consumption_id=_uuid(request.POST.get("consumption_id", "")),
            expected_revision=_revision(request),
        )
    elif action == "remove":
        _service().remove_section(
            actor=request.user,
            encounter_id=encounter_id,
            section_id=_uuid(request.POST.get("section_id", "")),
            expected_revision=_revision(request),
        )
    elif action == "discard":
        _service().discard_draft(actor=request.user, encounter_id=encounter_id, expected_revision=_revision(request))
        messages.success(request, gettext("Rascunho descartado."))
        return redirect("med_records:patient_section", organization_id, info.header.patient_id)
    elif action == "attach":
        upload = request.FILES.get("file")
        if upload is None:
            raise InvalidInput({"file": [gettext("Escolha um arquivo.")]})
        _service().attach_to_encounter(
            actor=request.user,
            encounter_id=encounter_id,
            filename="anexo",
            stream=upload,
            content_type=upload.content_type,
        )
        messages.success(request, gettext("Anexo incluído."))
    elif action == "template":
        _service().create_template(
            actor=request.user,
            name=(request.POST.get("template_name") or "").strip()[:120] or gettext("Modelo"),
            kind="encounter",
            sections=tuple(
                TemplateSectionInput(section.section_type, section.text, tuple(json.loads(section.data_json).items()))
                for section in info.sections
            ),
            personal=request.POST.get("personal") == "on",
            idempotency_key=_key(request),
        )
        messages.success(request, gettext("Modelo salvo."))
    elif action == "sign":
        signed = _service().sign_encounter(
            actor=request.user, encounter_id=encounter_id, expected_revision=_revision(request)
        )
        messages.success(request, gettext("Atendimento assinado."))
        if signed.header.appointment_id and not signed.appointment_completed:
            messages.warning(request, gettext("A consulta não foi concluída na agenda."))
        return redirect("med_records:encounter", organization_id, encounter_id)
    else:
        raise Http404
    return redirect("med_records:encounter_edit", organization_id, encounter_id)


@never_cache
@tenant_page()
def encounter_edit(request: HttpRequest, organization_id: UUID, encounter_id: UUID) -> HttpResponse:
    """The draft editor: one card per section, each with its own save button; sign at the end."""
    context = _encounter_context(request, organization_id, encounter_id)
    info = context["info"]
    if not info.writable:
        return redirect("med_records:encounter", organization_id, encounter_id)
    status = 200
    types = {item.code: item for item in active_section_types(request.user)}
    if request.method == "POST":
        try:
            with transaction.atomic():
                response = _encounter_post(request, organization_id, encounter_id, info, types)
            return response
        except (NotFound, Forbidden):
            raise Http404 from None
        except InvalidInput as error:
            messages.error(request, _errors(error))
        except Conflict as error:
            messages.error(request, conflict_text(error))
        status = 400
        context = _encounter_context(request, organization_id, encounter_id)
        info = context["info"]
    cards = []
    used: dict[str, int] = {}
    for section in info.sections:
        kind = SECTION_TYPES.get(section.section_type)
        used[section.section_type] = max(used.get(section.section_type, -1), section.position)
        if kind is None:
            continue
        initial = record_forms.section_initial(kind, json.loads(section.data_json), section.text)
        cards.append(
            {
                "section": section,
                "kind": kind,
                "position": section.position,
                "form": record_forms.section_form(kind, prefix="s", initial=initial),
            }
        )
    new = request.GET.get("add", "")
    if new in types:
        cards.append(
            {
                "section": None,
                "kind": types[new],
                "position": used.get(new, -1) + 1,
                "form": record_forms.section_form(types[new], prefix="s"),
            }
        )
    query = request.GET.get("cid", "")[:100]
    icd: tuple = ()
    if query.strip():
        try:
            icd = _service().search_icd10(actor=request.user, query=query)
        except InvalidInput:
            icd = ()
    try:
        consumables = _service().consumable_items(actor=request.user, encounter_id=encounter_id)
    except (NotFound, Forbidden):
        raise Http404 from None
    context.update(
        cards=cards,
        types=list(types.values()),
        query=query,
        icd=icd,
        idempotency_key=uuid.uuid4().hex,
        consumables=consumables,
    )
    return render(request, "med_records/encounter_edit.html", context, status=status)


@require_POST
@tenant_page()
def addendum(request: HttpRequest, organization_id: UUID, encounter_id: UUID) -> HttpResponse:
    form = record_forms.AddendumForm(request.POST)
    if not form.is_valid():
        messages.error(request, gettext("Escreva o texto do adendo."))
        return redirect("med_records:encounter", organization_id, encounter_id)
    try:
        with transaction.atomic():
            info = _service().add_addendum(
                actor=request.user,
                encounter_id=encounter_id,
                text=form.cleaned_data["text"],
                idempotency_key=_key(request),
            )
    except (NotFound, Forbidden):
        raise Http404 from None
    except Conflict as error:
        messages.error(request, conflict_text(error))
        return redirect("med_records:encounter", organization_id, encounter_id)
    return redirect("med_records:encounter_edit", organization_id, info.header.sysid)


# ------------------------------------------------------------------------------------ clinical lists


def _lists_post(request: HttpRequest, chart_id: UUID) -> tuple[bool, Any, Any]:
    kind = request.POST.get("form", "")
    allergy_form = medication_form = None
    if kind == "allergy":
        allergy_form = record_forms.AllergyForm(request.POST, prefix="allergy")
        if not allergy_form.is_valid():
            return False, allergy_form, None
        _service().add_allergy(
            actor=request.user, chart_id=chart_id, idempotency_key=_key(request), **allergy_form.cleaned_data
        )
    elif kind == "medication":
        medication_form = record_forms.MedicationForm(request.POST, prefix="medication")
        if not medication_form.is_valid():
            return False, None, medication_form
        _service().add_medication(
            actor=request.user, chart_id=chart_id, idempotency_key=_key(request), **medication_form.cleaned_data
        )
    elif kind in ("allergy_status", "medication_status"):
        target = _uuid(request.POST.get("id", ""))
        changes = (("status", request.POST.get("status", "")),)
        if kind == "allergy_status":
            _service().update_allergy(
                actor=request.user, allergy_id=target, changes=changes, expected_revision=_revision(request)
            )
        else:
            _service().update_medication(
                actor=request.user, medication_id=target, changes=changes, expected_revision=_revision(request)
            )
    else:
        raise Http404
    return True, None, None


@never_cache
@tenant_page()
def lists_view(request: HttpRequest, organization_id: UUID, chart_id: UUID) -> HttpResponse:
    try:
        chart = _service().chart(actor=request.user, chart_id=chart_id)
    except (NotFound, Forbidden):
        raise Http404 from None
    allergy_form = record_forms.AllergyForm(prefix="allergy")
    medication_form = record_forms.MedicationForm(prefix="medication")
    status = 200
    if request.method == "POST":
        status = 400
        try:
            with transaction.atomic():
                done, bad_allergy, bad_medication = _lists_post(request, chart_id)
            if done:
                return redirect("med_records:lists", organization_id, chart_id)
            allergy_form = bad_allergy or allergy_form
            medication_form = bad_medication or medication_form
        except (NotFound, Forbidden):
            raise Http404 from None
        except InvalidInput as error:
            messages.error(request, _errors(error))
        except Conflict as error:
            messages.error(request, conflict_text(error))
    return render(
        request,
        "med_records/lists.html",
        _context(
            organization_id,
            chart=chart,
            patient=_patient(request, chart.patient_id),
            allergies=_service().allergies(actor=request.user, chart_id=chart_id),
            medications=_service().medications(actor=request.user, chart_id=chart_id),
            allergy_form=allergy_form,
            medication_form=medication_form,
            idempotency_key=uuid.uuid4().hex,
        ),
        status=status,
    )


# ------------------------------------------------------------------------------------ documents


@require_POST
@tenant_page()
def document_new(request: HttpRequest, organization_id: UUID, chart_id: UUID) -> HttpResponse:
    form = record_forms.NewDocumentForm(
        request.POST,
        kinds=active_document_kinds(request.user),
        templates=_service().templates(actor=request.user, kind="document"),
    )
    if not form.is_valid():
        raise Http404
    template = form.cleaned_data["template"]
    try:
        with transaction.atomic():
            info = _service().draft_document(
                actor=request.user,
                chart_id=chart_id,
                kind=form.cleaned_data["kind"],
                template_id=_uuid(template) if template else None,
                idempotency_key=_key(request),
            )
    except (NotFound, Forbidden):
        raise Http404 from None
    except InvalidInput as error:
        messages.error(request, _errors(error))
        chart = _service().chart(actor=request.user, chart_id=chart_id)
        return redirect("med_records:patient_section", organization_id, chart.patient_id)
    return redirect("med_records:document_edit", organization_id, info.header.sysid)


def _document_context(
    request: HttpRequest, organization_id: UUID, document_id: UUID, *, printing: bool = False
) -> dict[str, Any]:
    try:
        info = _service().document(actor=request.user, document_id=document_id, printing=printing)
    except (NotFound, Forbidden):
        raise Http404 from None
    kind = next((item for item in active_document_kinds(request.user) if item.code == info.header.kind), None)
    return _context(
        organization_id,
        info=info,
        header=info.header,
        kind_label=kind.label if kind else info.header.kind,
        patient=_patient(request, info.header.patient_id),
        idempotency_key=uuid.uuid4().hex,
    )


@never_cache
@tenant_page()
def document_view(request: HttpRequest, organization_id: UUID, document_id: UUID) -> HttpResponse:
    context = _document_context(request, organization_id, document_id)
    try:
        panels = _service().document_panels(actor=request.user, document_id=document_id)
    except (NotFound, Forbidden):
        raise Http404 from None
    context["panels"] = _rendered_panels(request, organization_id, panels, document_id=context["header"].sysid)
    return render(request, "med_records/document.html", context)


@never_cache
@tenant_page()
def document_print(request: HttpRequest, organization_id: UUID, document_id: UUID) -> HttpResponse:
    from applications.med_scheduling.service_api import SchedulingService

    context = _document_context(request, organization_id, document_id, printing=True)
    if not context["header"].issued:
        raise Http404
    try:
        context["practice"] = SchedulingService().practice(actor=request.user)
    except (NotFound, Forbidden):
        context["practice"] = None
    return render(request, "med_records/document_print.html", context)


@never_cache
@tenant_page()
def document_edit(request: HttpRequest, organization_id: UUID, document_id: UUID) -> HttpResponse:
    context = _document_context(request, organization_id, document_id)
    info = context["info"]
    if not info.writable:
        return redirect("med_records:document", organization_id, document_id)
    form = record_forms.DocumentForm(request.POST or None, initial={"title": info.header.title, "body": info.body})
    status = 200
    if request.method == "POST":
        status = 400
        if form.is_valid():
            try:
                with transaction.atomic():
                    saved = _service().update_document(
                        actor=request.user,
                        document_id=document_id,
                        title=form.cleaned_data["title"],
                        body=form.cleaned_data["body"],
                        expected_revision=_revision(request),
                    )
                    if request.POST.get("action") == "issue":
                        _service().issue_document(
                            actor=request.user, document_id=document_id, expected_revision=saved.header.revision
                        )
            except (NotFound, Forbidden):
                raise Http404 from None
            except InvalidInput as error:
                record_forms.apply_service_errors(form, error)
            except Conflict as error:
                form.add_error(None, conflict_text(error))
            else:
                if request.POST.get("action") == "issue":
                    messages.success(request, gettext("Documento emitido."))
                    return redirect("med_records:document", organization_id, document_id)
                messages.success(request, gettext("Rascunho salvo."))
                return redirect("med_records:document_edit", organization_id, document_id)
    context["form"] = form
    return render(request, "med_records/document_edit.html", context, status=status)


@require_POST
@tenant_page()
def document_replace(request: HttpRequest, organization_id: UUID, document_id: UUID) -> HttpResponse:
    try:
        with transaction.atomic():
            info = _service().replace_document(
                actor=request.user, document_id=document_id, idempotency_key=_key(request)
            )
    except (NotFound, Forbidden):
        raise Http404 from None
    except Conflict as error:
        messages.error(request, conflict_text(error))
        return redirect("med_records:document", organization_id, document_id)
    return redirect("med_records:document_edit", organization_id, info.header.sysid)


# ------------------------------------------------------------------------------------ templates and trail


@tenant_page()
def templates_view(request: HttpRequest, organization_id: UUID) -> HttpResponse:
    if not _service().archives(actor=request.user):
        raise Http404
    form = record_forms.TemplateForm(request.POST or None, kinds=active_document_kinds(request.user))
    status = 200
    if request.method == "POST":
        status = 400
        try:
            with transaction.atomic():
                if request.POST.get("action") == "deactivate":
                    _service().update_template(
                        actor=request.user,
                        template_id=_uuid(request.POST.get("id", "")),
                        active=False,
                        expected_revision=_revision(request),
                    )
                    return redirect("med_records:templates", organization_id)
                if form.is_valid():
                    values = form.cleaned_data
                    _service().create_template(
                        actor=request.user,
                        name=values["name"],
                        kind="document",
                        specialty=values["specialty"],
                        document_kind=values["document_kind"],
                        body=values["body"],
                        personal=values["personal"],
                        idempotency_key=_key(request),
                    )
                    messages.success(request, gettext("Modelo salvo."))
                    return redirect("med_records:templates", organization_id)
        except (NotFound, Forbidden):
            raise Http404 from None
        except InvalidInput as error:
            record_forms.apply_service_errors(form, error)
        except Conflict as error:
            messages.error(request, conflict_text(error))
    return render(
        request,
        "med_records/templates.html",
        _context(
            organization_id,
            templates=_service().templates(actor=request.user),
            form=form,
            idempotency_key=uuid.uuid4().hex,
        ),
        status=status,
    )


def _origin(entry: Any) -> str:
    """Where a read came from, for the trail page: the credential, and the client of a native app."""
    labels = {
        "web": gettext("Sessão web"),
        "native_client": gettext("Cliente nativo"),
        "api_token": gettext("Token de API"),
    }
    label = labels.get(entry.origin, gettext("Outra"))
    return f"{label} ({entry.client_id})" if entry.client_id else label


@never_cache
@tenant_page()
def access_log_view(request: HttpRequest, organization_id: UUID, chart_id: UUID) -> HttpResponse:
    from skeleton.service_api.organizations import OrganizationService

    try:
        chart = _service().chart(actor=request.user, chart_id=chart_id)
        page = _service().access_log(
            actor=request.user, chart_id=chart_id, cursor=request.GET.get("cursor") or None, page_size=50
        )
    except (NotFound, Forbidden, InvalidInput):
        raise Http404 from None
    names = {
        member.sysid: member.display_name
        for member in OrganizationService().members(actor=request.user, page_size=100).items
    }
    return render(
        request,
        "med_records/access_log.html",
        _context(
            organization_id,
            chart=chart,
            entries=[
                {"entry": entry, "name": names.get(entry.actor_id, ""), "origin": _origin(entry)}
                for entry in page.items
            ],
            page=page,
        ),
    )
