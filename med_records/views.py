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
from skeleton.web.confirm import Confirmation, confirmation_step
from skeleton.web.views import tenant_page

from . import forms as record_forms
from .extension import SECTION_TYPES, active_document_kinds, active_section_types
from .sections import body_mass_index
from .service_api import ConsumptionInput, RecordsService, TemplateSectionInput

logger = logging.getLogger(__name__)


def confirmation_page(
    request: HttpRequest, confirmation: Confirmation, *, error: Any = "", status: int = 200
) -> HttpResponse:
    """The confirmation page of an action, again, with the reason it was refused (#119).

    The core's ``confirmation_step`` shows it on GET; a POST refused by the service (revision, state)
    shows it once more with the message, from the same ``Confirmation`` and the same template.
    """
    return render(
        request,
        confirmation.template,
        {
            "title": confirmation.title,
            "message": confirmation.message,
            "submit_label": confirmation.submit_label,
            "cancel_url": confirmation.cancel_url,
            "subject_label": confirmation.subject,
            "eyebrow": confirmation.eyebrow,
            "hidden": sorted(confirmation.hidden.items()),
            "reason_label": confirmation.reason_label,
            "reason_required": confirmation.reason_required,
            "error": error,
            **confirmation.context,
        },
        status=status,
    )


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
            value = f"{value} {field.unit}"  # The unit never wraps away from its number.
        # A date stays in ISO: the template shows it with |moment.
        rows.append({"label": field.label, "value": value, "kind": field.kind})
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
                prefix="encounter",
                templates=_service().templates(actor=request.user, archive_id=archive.sysid, kind="encounter"),
            ),
            document_form=record_forms.NewDocumentForm(
                prefix="document",
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
        request.POST, prefix="encounter", templates=_service().templates(actor=request.user, kind="encounter")
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


ICD_LIST = "icd10_list"


def _card_prefix(index: int) -> str:
    return f"s{index}"


def _stored_cards(info: Any) -> list[dict[str, Any]]:
    """The cards of the stored sections, in order, with the values they were saved with."""
    cards = []
    for section in info.sections:
        kind = SECTION_TYPES.get(section.section_type)
        if kind is None:
            continue
        cards.append(
            {
                "section": section,
                "kind": kind,
                "position": section.position,
                "initial": record_forms.section_initial(kind, json.loads(section.data_json), section.text),
            }
        )
    return cards


def _posted_cards(request: HttpRequest, info: Any, types: dict) -> list[dict[str, Any]]:
    """The cards the editor sent: a stored section by its id, or a new one by type and position."""
    stored = {str(card["section"].sysid): card for card in _stored_cards(info)}
    try:
        count = min(int(request.POST.get("cards", "0")), 60)
    except ValueError:
        count = 0
    cards = []
    for index in range(count):
        prefix = _card_prefix(index)
        section_id = request.POST.get(f"{prefix}-section", "")
        if section_id:
            card = stored.get(section_id)
            if card is None:
                continue  # Removed meanwhile: the revision check of the next write reports it.
            card = dict(card)
        else:
            kind = types.get(request.POST.get(f"{prefix}-type", ""))
            if kind is None:
                raise Http404
            try:
                position = int(request.POST.get(f"{prefix}-position", "0"))
            except ValueError:
                position = 0
            card = {"section": None, "kind": kind, "position": position, "initial": {}}
        card["form"] = record_forms.section_form(card["kind"], request.POST, prefix=prefix, initial=card["initial"])
        cards.append(card)
    return cards


def _use_icd(request: HttpRequest, cards: list[dict[str, Any]], code: str) -> bool:
    """Append the chosen ICD-10 code to the first diagnoses field of the posted cards."""
    try:
        found = _service().search_icd10(actor=request.user, query=code)
    except InvalidInput:
        return False
    item = next((row for row in found if row.code == code), None)
    if item is None:
        return False
    for card in cards:
        for field in card["kind"].fields:
            if field.kind == ICD_LIST:
                form = card["form"]
                name = form.add_prefix(field.name)
                data = form.data.copy()
                current = (data.get(name) or "").rstrip()
                data[name] = f"{current}\n{item.code} {item.description}".strip()
                card["form"] = record_forms.section_form(
                    card["kind"], data, prefix=form.prefix, initial=card["initial"]
                )
                return True
    return False


def _save_cards(request: HttpRequest, encounter_id: UUID, cards: list[dict[str, Any]], revision: int) -> int:
    """Save every card that changed, in order; return the revision after the last save."""
    for card in cards:
        form = card["form"]
        if card["section"] is not None and not form.has_changed():
            continue
        data = record_forms.section_data(card["kind"], form.cleaned_data)
        text = form.cleaned_data.get("text", "") or ""
        if card["section"] is None and not data and not text.strip():
            card["pending"] = True  # A new card left empty is not a section: the page keeps it open.
            continue
        info = _service().save_section(
            actor=request.user,
            encounter_id=encounter_id,
            section_type=card["kind"].code,
            data=data,
            text=text,
            position=card["position"],
            expected_revision=revision,
        )
        revision = info.header.revision
    return revision


def _encounter_action(
    request: HttpRequest, organization_id: UUID, encounter_id: UUID, action: str, revision: int
) -> HttpResponse | None:
    """Run the action of the button after the sections were saved; ``None`` renders the editor again."""
    kind, _sep, target = action.partition(":")
    if kind == "remove":
        return redirect("med_records:section_remove", organization_id, encounter_id, _uuid(target))
    elif kind == "consumption_add":
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
            expected_revision=revision,
        )
        messages.success(request, gettext("Item consumido incluído."))
    elif kind == "consumption_remove":
        _service().remove_consumption(
            actor=request.user, encounter_id=encounter_id, consumption_id=_uuid(target), expected_revision=revision
        )
        messages.success(request, gettext("Item consumido removido."))
    elif kind == "attach":
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
    elif kind == "template":
        current = _service().encounter(actor=request.user, encounter_id=encounter_id)
        _service().create_template(
            actor=request.user,
            name=(request.POST.get("template_name") or "").strip()[:120] or gettext("Modelo"),
            kind="encounter",
            sections=tuple(
                TemplateSectionInput(section.section_type, section.text, tuple(json.loads(section.data_json).items()))
                for section in current.sections
            ),
            personal=request.POST.get("personal") == "on",
            idempotency_key=_key(request),
        )
        messages.success(request, gettext("Modelo salvo."))
    elif kind == "add":
        response = redirect("med_records:encounter_edit", organization_id, encounter_id)
        new = request.POST.get("add_type", "")
        if new:
            response["Location"] += f"?add={new}"
        return response
    elif kind == "sign":
        return redirect("med_records:encounter_sign", organization_id, encounter_id)
    elif kind == "save":
        messages.success(request, gettext("Rascunho salvo."))
    elif kind in ("search", "use_icd"):
        return None
    else:
        raise Http404
    return redirect("med_records:encounter_edit", organization_id, encounter_id)


def _editor_page(
    request: HttpRequest,
    organization_id: UUID,
    encounter_id: UUID,
    context: dict[str, Any],
    types: dict,
    *,
    cards: list[dict[str, Any]] | None = None,
    pending: tuple[dict[str, Any], ...] = (),
    query: str = "",
    status: int = 200,
) -> HttpResponse:
    info = context["info"]
    if cards is None:
        cards = _stored_cards(info)
        cards += [{**card, "initial": {}} for card in pending]
        used: dict[str, int] = {}
        for section in info.sections:
            used[section.section_type] = max(used.get(section.section_type, -1), section.position)
        new = request.GET.get("add", "")
        if new in types:
            cards.append({"section": None, "kind": types[new], "position": used.get(new, -1) + 1, "initial": {}})
        for index, card in enumerate(cards):
            card["form"] = record_forms.section_form(card["kind"], prefix=_card_prefix(index), initial=card["initial"])
    for index, card in enumerate(cards):
        card["prefix"] = _card_prefix(index)
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
        has_icd=any(field.kind == ICD_LIST for card in cards for field in card["kind"].fields),
        idempotency_key=uuid.uuid4().hex,
        consumables=consumables,
    )
    return render(request, "med_records/encounter_edit.html", context, status=status)


@never_cache
@tenant_page()
def encounter_edit(request: HttpRequest, organization_id: UUID, encounter_id: UUID) -> HttpResponse:
    """The draft editor: one form for every section; each button saves what was typed, then acts."""
    context = _encounter_context(request, organization_id, encounter_id)
    info = context["info"]
    if not info.writable:
        return redirect("med_records:encounter", organization_id, encounter_id)
    types = {item.code: item for item in active_section_types(request.user)}
    if request.method != "POST":
        return _editor_page(request, organization_id, encounter_id, context, types)
    action = request.POST.get("action", "save")
    cards = _posted_cards(request, info, types)
    query = (request.POST.get("cid") or "")[:100]
    if action.startswith("use_icd:") and not _use_icd(request, cards, action.partition(":")[2]):
        messages.error(request, gettext("Acrescente a seção de hipóteses diagnósticas para usar o código."))
    if not all(card["form"].is_valid() for card in cards):
        context["form_error"] = gettext("Confira os campos marcados. Nada foi salvo.")
        return _editor_page(
            request, organization_id, encounter_id, context, types, cards=cards, query=query, status=400
        )
    try:
        with transaction.atomic():
            revision = _save_cards(request, encounter_id, cards, _revision(request))
            response = _encounter_action(request, organization_id, encounter_id, action, revision)
    except (NotFound, Forbidden):
        raise Http404 from None
    except InvalidInput as error:
        context["form_error"] = _errors(error)
    except Conflict as error:
        context["form_error"] = conflict_text(error)
    else:
        if response is not None:
            return response
        context = _encounter_context(request, organization_id, encounter_id)
        pending = tuple(card for card in cards if card.get("pending"))
        return _editor_page(request, organization_id, encounter_id, context, types, pending=pending, query=query)
    # One transaction: nothing was saved. The page keeps what was typed, with the reason.
    return _editor_page(request, organization_id, encounter_id, context, types, cards=cards, query=query, status=400)


def _describe_sign(request: HttpRequest, organization_id: UUID, encounter_id: UUID) -> Confirmation:
    from django.urls import reverse

    context = _encounter_context(request, organization_id, encounter_id)
    header = context["header"]
    labels = ", ".join(str(row["label"]) for row in context["sections"]) or gettext("nenhuma")
    return Confirmation(
        title=gettext("Assinar o atendimento"),
        eyebrow=header.code,
        message=gettext(
            "Depois de assinado, o atendimento não muda nem é excluído: uma correção só entra por adendo. "
            "Seções que serão seladas: %(sections)s."
        )
        % {"sections": labels},
        submit_label=gettext("Assinar o atendimento"),
        cancel_url=reverse("med_records:encounter_edit", args=(organization_id, encounter_id)),
        hidden={"revision": header.revision},
    )


@never_cache
@tenant_page()
@confirmation_step(_describe_sign)
@require_POST
def encounter_sign(request: HttpRequest, organization_id: UUID, encounter_id: UUID) -> HttpResponse:
    try:
        with transaction.atomic():
            signed = _service().sign_encounter(
                actor=request.user, encounter_id=encounter_id, expected_revision=_revision(request)
            )
    except (NotFound, Forbidden):
        raise Http404 from None
    except (Conflict, InvalidInput) as error:
        text = conflict_text(error) if isinstance(error, Conflict) else _errors(error)
        confirmation = _describe_sign(request, organization_id, encounter_id)
        return confirmation_page(request, confirmation, error=text, status=409)
    messages.success(request, gettext("Atendimento assinado."))
    if signed.header.appointment_id and not signed.appointment_completed:
        messages.warning(request, gettext("A consulta não foi concluída na agenda."))
    return redirect("med_records:encounter", organization_id, encounter_id)


def _describe_section_remove(
    request: HttpRequest, organization_id: UUID, encounter_id: UUID, section_id: UUID
) -> Confirmation:
    from django.urls import reverse

    context = _encounter_context(request, organization_id, encounter_id)
    row = next((item for item in context["sections"] if item["section"].sysid == section_id), None)
    if row is None or not context["info"].writable:
        raise Http404
    return Confirmation(
        title=gettext("Remover a seção"),
        eyebrow=context["header"].code,
        subject=str(row["label"]),
        message=gettext("A seção e o que foi escrito nela saem do rascunho."),
        submit_label=gettext("Remover a seção"),
        cancel_url=reverse("med_records:encounter_edit", args=(organization_id, encounter_id)),
        hidden={"revision": context["header"].revision},
    )


@never_cache
@tenant_page()
@confirmation_step(_describe_section_remove)
@require_POST
def section_remove(request: HttpRequest, organization_id: UUID, encounter_id: UUID, section_id: UUID) -> HttpResponse:
    try:
        with transaction.atomic():
            _service().remove_section(
                actor=request.user,
                encounter_id=encounter_id,
                section_id=section_id,
                expected_revision=_revision(request),
            )
    except (NotFound, Forbidden):
        raise Http404 from None
    except Conflict as error:
        confirmation = _describe_section_remove(request, organization_id, encounter_id, section_id)
        return confirmation_page(request, confirmation, error=conflict_text(error), status=409)
    messages.success(request, gettext("Seção removida."))
    return redirect("med_records:encounter_edit", organization_id, encounter_id)


def _describe_discard(request: HttpRequest, organization_id: UUID, encounter_id: UUID) -> Confirmation:
    from django.urls import reverse

    header = _encounter_context(request, organization_id, encounter_id)["header"]
    return Confirmation(
        title=gettext("Descartar o rascunho"),
        eyebrow=header.code,
        message=gettext("O rascunho e as seções dele saem do prontuário. Isso não se desfaz."),
        submit_label=gettext("Descartar o rascunho"),
        cancel_url=reverse("med_records:encounter_edit", args=(organization_id, encounter_id)),
        hidden={"revision": header.revision},
    )


@never_cache
@tenant_page()
@confirmation_step(_describe_discard)
@require_POST
def encounter_discard(request: HttpRequest, organization_id: UUID, encounter_id: UUID) -> HttpResponse:
    header = _encounter_context(request, organization_id, encounter_id)["header"]
    try:
        with transaction.atomic():
            _service().discard_draft(
                actor=request.user, encounter_id=encounter_id, expected_revision=_revision(request)
            )
    except (NotFound, Forbidden):
        raise Http404 from None
    except Conflict as error:
        confirmation = _describe_discard(request, organization_id, encounter_id)
        return confirmation_page(request, confirmation, error=conflict_text(error), status=409)
    messages.success(request, gettext("Rascunho descartado."))
    return redirect("med_records:patient_section", organization_id, header.patient_id)


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


LIST_ENDINGS = {
    # kind: (status written, title, message)
    "allergy": (
        "resolved",
        gettext("Marcar a alergia como resolvida"),
        gettext("A alergia sai do destaque do prontuário e dos avisos ao prescrever. Ela continua no histórico."),
    ),
    "medication": (
        "ended",
        gettext("Encerrar o medicamento"),
        gettext("O medicamento sai da lista de medicamentos em uso. Ele continua no histórico."),
    ),
}


def _list_item(request: HttpRequest, chart_id: UUID, kind: str, item_id: UUID) -> Any:
    try:
        items = (
            _service().allergies(actor=request.user, chart_id=chart_id)
            if kind == "allergy"
            else _service().medications(actor=request.user, chart_id=chart_id)
        )
    except (NotFound, Forbidden):
        raise Http404 from None
    item = next((row for row in items if row.sysid == item_id and row.status == "active"), None)
    if item is None:
        raise Http404
    return item


def _describe_list_end(request: HttpRequest, organization_id: UUID, chart_id: UUID, kind: str, item_id: UUID) -> Any:
    from django.urls import reverse

    if kind not in LIST_ENDINGS:
        raise Http404
    item = _list_item(request, chart_id, kind, item_id)
    _status, title, message = LIST_ENDINGS[kind]
    return Confirmation(
        title=title,
        subject=item.substance if kind == "allergy" else item.name,
        message=message,
        submit_label=title,
        cancel_url=reverse("med_records:lists", args=(organization_id, chart_id)),
        hidden={"revision": item.revision},
    )


@never_cache
@tenant_page()
@confirmation_step(_describe_list_end)
@require_POST
def list_end(request: HttpRequest, organization_id: UUID, chart_id: UUID, kind: str, item_id: UUID) -> HttpResponse:
    """Resolve an allergy or end a medication of the chart (#119)."""
    if kind not in LIST_ENDINGS:
        raise Http404
    _list_item(request, chart_id, kind, item_id)
    status, _title, _message = LIST_ENDINGS[kind]
    changes = (("status", status),)
    try:
        with transaction.atomic():
            if kind == "allergy":
                _service().update_allergy(
                    actor=request.user, allergy_id=item_id, changes=changes, expected_revision=_revision(request)
                )
            else:
                _service().update_medication(
                    actor=request.user, medication_id=item_id, changes=changes, expected_revision=_revision(request)
                )
    except (NotFound, Forbidden):
        raise Http404 from None
    except (Conflict, InvalidInput) as error:
        messages.error(request, conflict_text(error) if isinstance(error, Conflict) else _errors(error))
    else:
        messages.success(
            request,
            gettext("Alergia marcada como resolvida.") if kind == "allergy" else gettext("Medicamento encerrado."),
        )
    return redirect("med_records:lists", organization_id, chart_id)


# ------------------------------------------------------------------------------------ documents


@require_POST
@tenant_page()
def document_new(request: HttpRequest, organization_id: UUID, chart_id: UUID) -> HttpResponse:
    form = record_forms.NewDocumentForm(
        request.POST,
        prefix="document",
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
                    _service().update_document(
                        actor=request.user,
                        document_id=document_id,
                        title=form.cleaned_data["title"],
                        body=form.cleaned_data["body"],
                        expected_revision=_revision(request),
                    )
            except (NotFound, Forbidden):
                raise Http404 from None
            except InvalidInput as error:
                record_forms.apply_service_errors(form, error)
            except Conflict as error:
                form.add_error(None, conflict_text(error))
            else:
                if request.POST.get("action") == "issue":
                    return redirect("med_records:document_issue", organization_id, document_id)
                messages.success(request, gettext("Rascunho salvo."))
                return redirect("med_records:document_edit", organization_id, document_id)
    context["form"] = form
    return render(request, "med_records/document_edit.html", context, status=status)


def _describe_issue(request: HttpRequest, organization_id: UUID, document_id: UUID) -> Confirmation:
    from django.urls import reverse

    context = _document_context(request, organization_id, document_id)
    header = context["header"]
    if not context["info"].writable:
        raise Http404
    return Confirmation(
        title=gettext("Emitir o documento"),
        eyebrow=f"{header.code} · {context['kind_label']}",
        subject=header.title,
        message=gettext(
            "Emitido, o documento é selado e não muda mais: uma correção só sai por um documento que o substitui."
        ),
        submit_label=gettext("Emitir o documento"),
        cancel_url=reverse("med_records:document_edit", args=(organization_id, document_id)),
        hidden={"revision": header.revision},
    )


@never_cache
@tenant_page()
@confirmation_step(_describe_issue)
@require_POST
def document_issue(request: HttpRequest, organization_id: UUID, document_id: UUID) -> HttpResponse:
    try:
        with transaction.atomic():
            _service().issue_document(actor=request.user, document_id=document_id, expected_revision=_revision(request))
    except (NotFound, Forbidden):
        raise Http404 from None
    except (Conflict, InvalidInput) as error:
        text = conflict_text(error) if isinstance(error, Conflict) else _errors(error)
        return confirmation_page(
            request, _describe_issue(request, organization_id, document_id), error=text, status=409
        )
    messages.success(request, gettext("Documento emitido."))
    return redirect("med_records:document", organization_id, document_id)


def _describe_replace(request: HttpRequest, organization_id: UUID, document_id: UUID) -> Confirmation:
    from django.urls import reverse

    context = _document_context(request, organization_id, document_id)
    header = context["header"]
    if not header.issued or header.replaced_by_code:
        raise Http404
    return Confirmation(
        title=gettext("Substituir o documento"),
        eyebrow=f"{header.code} · {context['kind_label']}",
        subject=header.title,
        message=gettext(
            "Um rascunho novo nasce com o texto deste documento. Quando ele for emitido, este passa a constar "
            "como substituído; o original continua guardado."
        ),
        submit_label=gettext("Criar o rascunho substituto"),
        cancel_url=reverse("med_records:document", args=(organization_id, document_id)),
        hidden={"idempotency_key": uuid.uuid4().hex},
    )


@never_cache
@tenant_page()
@confirmation_step(_describe_replace)
@require_POST
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


def _describe_template_deactivate(request: HttpRequest, organization_id: UUID, template_id: UUID) -> Confirmation:
    from django.urls import reverse

    item = next((row for row in _service().templates(actor=request.user) if row.sysid == template_id), None)
    if item is None:
        raise Http404
    return Confirmation(
        title=gettext("Desativar o modelo"),
        subject=item.name,
        message=gettext(
            "O modelo deixa de aparecer ao iniciar atendimentos e documentos. O que já foi escrito não muda."
        ),
        submit_label=gettext("Desativar o modelo"),
        cancel_url=reverse("med_records:templates", args=(organization_id,)),
        hidden={"revision": item.revision},
    )


@tenant_page()
@confirmation_step(_describe_template_deactivate)
@require_POST
def template_deactivate(request: HttpRequest, organization_id: UUID, template_id: UUID) -> HttpResponse:
    _describe_template_deactivate(request, organization_id, template_id)
    try:
        with transaction.atomic():
            _service().update_template(
                actor=request.user, template_id=template_id, active=False, expected_revision=_revision(request)
            )
    except (NotFound, Forbidden):
        raise Http404 from None
    except Conflict as error:
        messages.error(request, conflict_text(error))
    else:
        messages.success(request, gettext("Modelo desativado."))
    return redirect("med_records:templates", organization_id)


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
    next_url = ""
    if page.next_cursor:
        query = request.GET.copy()
        query["cursor"] = page.next_cursor
        next_url = f"?{query.urlencode()}"  # The cursor is opaque text: always encoded (#123).
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
            next_url=next_url,
        ),
    )
