"""Pages of the finance app: every read and write goes through FinanceService (and the other apps' services).

Amounts are typed in reais and shown with the ``brl`` filter; the service keeps integer centavos.
A desk, charge or receipt the actor cannot read answers 404.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any
from uuid import UUID

from django.contrib import messages
from django.db import transaction
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.utils.translation import gettext
from django.views.decorators.http import require_POST

from applications.med_patients.service_api import PatientService
from skeleton.service_api import Conflict, Forbidden, InvalidInput, NotFound
from skeleton.web.confirm import Confirmation, confirmation_step
from skeleton.web.views import tenant_page

from . import forms as finance_forms
from .service_api import ChargeItemInput, FinanceService

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


def _service() -> FinanceService:
    return FinanceService()


def conflict_text(error: Conflict) -> str:
    texts = {
        "stale_revision": gettext("O registro mudou desde que a página abriu. Atualize a página e tente de novo."),
        "session_already_open": gettext("Este caixa já tem uma sessão aberta."),
        "session_closed": gettext("A sessão do caixa está fechada."),
        "insufficient_cash": gettext("A sangria é maior que o dinheiro esperado no caixa."),
        "no_open_session": gettext("Abra o caixa antes de receber."),
        "not_open": gettext("Só uma conta em aberto recebe pagamento."),
        "has_payments": gettext("Estorne os pagamentos antes de cancelar a conta."),
        "receipt_not_voided": gettext("Anule o recibo antes de estornar o pagamento."),
        "ledger_rejected": gettext("O livro contábil recusou o lançamento (período travado ou conta não vinculada)."),
        "already_set_up": gettext("O financeiro já foi configurado nesta organização."),
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


def _context(organization_id: UUID, **values: Any) -> dict[str, Any]:
    return {"organization_id": organization_id, **values}


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
        except Exception as exc:  # noqa: BLE001 - one app's panel never breaks the page
            logger.warning("med_finance.panel_failed", extra={"contribution": panel.code, "error": type(exc).__name__})
            continue
        shown.append({"code": panel.code, "label": panel.label, "url": "", "html": html})
    return shown


def _patients(request: HttpRequest, ids: list[UUID]) -> dict[UUID, Any]:
    if not ids:
        return {}
    try:
        found = PatientService().summaries(actor=request.user, patient_ids=tuple(dict.fromkeys(ids))[:200])
    except (NotFound, Forbidden):
        return {}
    return {item.sysid: item for item in found}


def _run(request: HttpRequest, action: Any, success: str) -> bool:
    """Run a service command in a transaction; show the outcome as a message. 404 for unreadable."""
    try:
        with transaction.atomic():
            action()
    except (NotFound, Forbidden):
        raise Http404 from None
    except InvalidInput as error:
        messages.error(request, _errors(error))
        return False
    except Conflict as error:
        messages.error(request, conflict_text(error))
        return False
    messages.success(request, success)
    return True


def _form_run(form: Any, action: Any) -> bool:
    """Run a service command in a transaction; a refusal goes on the form, which keeps what was typed."""
    try:
        with transaction.atomic():
            action()
    except (NotFound, Forbidden):
        raise Http404 from None
    except InvalidInput as error:
        finance_forms.apply_service_errors(form, error)
        return False
    except Conflict as error:
        form.add_error(None, conflict_text(error))
        return False
    return True


# ------------------------------------------------------------------------------------ desk


@tenant_page()
def desk_view(
    request: HttpRequest, organization_id: UUID, *, forms: dict[str, Any] | None = None, status: int = 200
) -> HttpResponse:
    """The cash desk of the day: the session, its totals and movements, and the charges open until today.

    The list is the desk's charges with a balance to receive due today or earlier (#132), not the last ones created.
    """
    from django.utils import timezone

    from skeleton.service_api.access import AccessService

    desks = _service().desks(actor=request.user)
    if not desks:
        manager = "access.manage" in AccessService().capabilities(actor=request.user)
        return render(request, "med_finance/empty.html", _context(organization_id, manager=manager))
    desk = desks[0]
    session = _service().current_session(actor=request.user, desk_id=desk.sysid)
    report = _service().session_report(actor=request.user, session_id=session.sysid) if session else None
    today = timezone.localdate()
    page = _service().charges(actor=request.user, desk_id=desk.sysid, outstanding=True, end=today, page_size=30)
    charges = page.items
    names = _patients(request, [item.patient_id for item in charges])
    return render(
        request,
        "med_finance/desk.html",
        _context(
            organization_id,
            desk=desk,
            session=session,
            report=report,
            charges=[{"charge": item, "patient": names.get(item.patient_id)} for item in charges],
            more_charges=bool(page.next_cursor),
            outstanding_query=_charges_query(status=OUTSTANDING, due_to=today),
            open_form=finance_forms.OpenSessionForm(),
            movement_form=finance_forms.MovementForm(),
            close_form=finance_forms.CloseSessionForm(),
            idempotency_key=uuid.uuid4().hex,
            **(forms or {}),
        ),
        status=status,
    )


@require_POST
@tenant_page()
def session_open(request: HttpRequest, organization_id: UUID) -> HttpResponse:
    form = finance_forms.OpenSessionForm(request.POST)
    if form.is_valid():
        _run(
            request,
            lambda: _service().open_session(
                actor=request.user,
                opening_amount=form.cleaned_data["opening_amount"] or 0,
                idempotency_key=_key(request),
            ),
            gettext("Caixa aberto."),
        )
    else:
        messages.error(request, " ".join(str(error) for errors in form.errors.values() for error in errors))
    return redirect("med_finance:desk", organization_id)


@require_POST
@tenant_page()
def session_movement(request: HttpRequest, organization_id: UUID, session_id: UUID) -> HttpResponse:
    form = finance_forms.MovementForm(request.POST)
    if form.is_valid() and _form_run(
        form,
        lambda: _service().add_movement(
            actor=request.user,
            session_id=session_id,
            kind=form.cleaned_data["kind"],
            amount=form.cleaned_data["amount"],
            reason=form.cleaned_data["reason"],
            idempotency_key=_key(request),
        ),
    ):
        messages.success(request, gettext("Movimento registrado."))
        return redirect("med_finance:desk", organization_id)
    return desk_view(request, organization_id=organization_id, forms={"movement_form": form}, status=400)


@require_POST
@tenant_page()
def session_close(request: HttpRequest, organization_id: UUID, session_id: UUID) -> HttpResponse:
    """Close the session in two steps (#119): what was counted against what is expected, then the close."""
    from django.urls import reverse

    from .templatetags.med_finance_format import brl

    form = finance_forms.CloseSessionForm(request.POST)
    if not form.is_valid():
        return desk_view(request, organization_id=organization_id, forms={"close_form": form}, status=400)
    counted = form.cleaned_data["counted_amount"]
    if request.POST.get("confirmed") != "1":
        try:
            report = _service().session_report(actor=request.user, session_id=session_id)
        except (NotFound, Forbidden):
            raise Http404 from None
        difference = counted - report.expected_cash
        if difference == 0:
            outcome = gettext("O caixa fecha sem diferença.")
        elif difference > 0:
            outcome = gettext("Sobram %(amount)s.") % {"amount": brl(difference)}
        else:
            outcome = gettext("Faltam %(amount)s.") % {"amount": brl(-difference)}
        message = gettext(
            "Esperado em dinheiro: %(expected)s. Contado: %(counted)s. %(outcome)s "
            "Fechado, o caixa não recebe mais pagamentos nem movimentos."
        ) % {"expected": brl(report.expected_cash), "counted": brl(counted), "outcome": outcome}
        confirmation = Confirmation(
            title=gettext("Fechar o caixa"),
            message=message,
            submit_label=gettext("Fechar o caixa"),
            cancel_url=reverse("med_finance:desk", args=(organization_id,)),
            hidden={
                "confirmed": "1",
                "revision": request.POST.get("revision", ""),
                "counted_amount": request.POST.get("counted_amount", ""),
                "note": form.cleaned_data["note"],
            },
        )
        return confirmation_page(request, confirmation)
    if _form_run(
        form,
        lambda: _service().close_session(
            actor=request.user,
            session_id=session_id,
            counted_amount=counted,
            note=form.cleaned_data["note"],
            expected_revision=_revision(request),
        ),
    ):
        messages.success(request, gettext("Caixa fechado."))
        return redirect("med_finance:session", organization_id, session_id)
    return desk_view(request, organization_id=organization_id, forms={"close_form": form}, status=400)


@tenant_page()
def session_view(request: HttpRequest, organization_id: UUID, session_id: UUID) -> HttpResponse:
    try:
        report = _service().session_report(actor=request.user, session_id=session_id)
    except (NotFound, Forbidden):
        raise Http404 from None
    return render(request, "med_finance/session.html", _context(organization_id, report=report))


# ------------------------------------------------------------------------------------ charges


# The status filter of the charges page: a status of the model, or "outstanding" (open or partially paid).
OUTSTANDING = "outstanding"


def _charges_query(*, status: str = "", due_from: Any = None, due_to: Any = None) -> str:
    """The query string of the charges page for a filter (the desk and the receivables link to it, #132)."""
    from django.utils.http import urlencode

    values = {
        "status": status,
        "due_from": due_from.isoformat() if due_from else "",
        "due_to": due_to.isoformat() if due_to else "",
    }
    return urlencode({name: value for name, value in values.items() if value})


def _query_date(request: HttpRequest, name: str) -> Any:
    from datetime import date as day_type

    value = request.GET.get(name) or ""
    if not value:
        return None
    try:
        return day_type.fromisoformat(value)
    except ValueError:
        raise Http404 from None


@tenant_page()
def charges_view(request: HttpRequest, organization_id: UUID) -> HttpResponse:
    """The charges, filtered by status ("A receber" too) and due dates; the filter travels in the query string."""
    from django.utils.http import urlencode

    from .models import Charge

    status = request.GET.get("status") or ""
    due_from = _query_date(request, "due_from")
    due_to = _query_date(request, "due_to")
    try:
        page = _service().charges(
            actor=request.user,
            status=None if status in ("", OUTSTANDING) else status,
            outstanding=status == OUTSTANDING,
            start=due_from,
            end=due_to,
            cursor=request.GET.get("cursor") or None,
            page_size=50,
        )
    except InvalidInput:
        raise Http404 from None
    names = _patients(request, [item.patient_id for item in page.items])
    query = _charges_query(status=status, due_from=due_from, due_to=due_to)
    next_url = ""
    if page.next_cursor:
        next_url = "?" + "&".join(part for part in (query, urlencode({"cursor": page.next_cursor})) if part)
    return render(
        request,
        "med_finance/charges.html",
        _context(
            organization_id,
            page=page,
            status=status,
            due_from=due_from,
            due_to=due_to,
            filtered=bool(query),
            status_options=((OUTSTANDING, gettext("A receber (em aberto ou parcial)")), *Charge.Status.choices),
            next_url=next_url,
            rows=[{"charge": item, "patient": names.get(item.patient_id)} for item in page.items],
        ),
    )


@tenant_page()
def charge_new(request: HttpRequest, organization_id: UUID) -> HttpResponse:
    desks = _service().desks(actor=request.user)
    if not desks:
        raise Http404
    query = request.GET.get("q", "")[:200]
    patient = None
    patient_id = request.GET.get("patient") or request.POST.get("patient") or ""
    if patient_id:
        try:
            patient = PatientService().summary(actor=request.user, patient_id=_uuid(patient_id))
        except NotFound:
            raise Http404 from None
    patients = PatientService().search(actor=request.user, query=query, page_size=20).items if query else ()
    prices = _service().price_items(actor=request.user) if desks[0].price_list_id else ()
    # "Item da tabela" or "Descrição livre" (#132): the choice travels in the query string and in the form.
    mode = request.POST.get("mode") or request.GET.get("mode") or ""
    if mode not in ("table", "free"):
        mode = "table" if prices else "free"
    if not prices:
        mode = "free"
    item_form = finance_forms.TableItemForm if mode == "table" else finance_forms.FreeItemForm
    posted = request.method == "POST" and patient is not None
    try:
        count = int(request.POST.get("rows", "1")) if posted else 1
    except ValueError:
        count = 1
    count = min(max(count, 1), finance_forms.MAX_ITEMS)
    adding = posted and "add_row" in request.POST and count < finance_forms.MAX_ITEMS
    form = finance_forms.ChargeForm(request.POST if posted and not adding else None, initial=_typed(request, "", ()))
    if adding:
        # "Acrescentar item": the same page with one more line and what was typed, nothing validated yet.
        count += 1
        rows = [_item_row(request, item_form, index, prices, bound=False) for index in range(count)]
    else:
        rows = [_item_row(request, item_form, index, prices, bound=posted) for index in range(count)]
    status = 200
    item_errors: list[str] = []
    if posted and not adding:
        status = 400
        filled = [row for row in rows if row.has_changed()]
        rows_valid = all(row.is_valid() for row in rows)
        if not filled:
            item_errors.append(gettext("Informe ao menos um item."))
        for index, row in enumerate(rows, start=1):
            for field in row:
                for error in field.errors:
                    item_errors.append(
                        gettext("Item %(number)s · %(field)s: %(error)s")
                        % {"number": index, "field": field.label, "error": error}
                    )
        if form.is_valid() and rows_valid and filled:
            values = form.cleaned_data
            items = tuple(
                ChargeItemInput(
                    code=row.cleaned_data.get("code", ""),
                    description=row.cleaned_data.get("description", ""),
                    quantity=row.cleaned_data["quantity"],
                    unit_amount=row.cleaned_data.get("unit_amount"),
                    discount_amount=row.cleaned_data["discount_amount"] or 0,
                )
                for row in filled
            )
            try:
                with transaction.atomic():
                    detail = _service().create_charge(
                        actor=request.user,
                        patient_id=patient.sysid,
                        items=items,
                        payer_name=values["payer_name"],
                        payer_document=values["payer_document"],
                        idempotency_key=_key(request),
                    )
            except (NotFound, Forbidden):
                raise Http404 from None
            except InvalidInput as error:
                finance_forms.apply_service_errors(form, error)
            except Conflict as error:
                form.add_error(None, conflict_text(error))
            else:
                messages.success(request, gettext("Conta criada."))
                return redirect("med_finance:charge", organization_id, detail.charge.sysid)
    modes = ()
    if patient is not None and prices:
        from django.utils.http import urlencode

        modes = tuple(
            {
                "url": "?" + urlencode({"patient": patient.sysid, "mode": value}),
                "label": label,
                "current": mode == value,
            }
            for value, label in (("table", gettext("Item da tabela")), ("free", gettext("Descrição livre")))
        )
    return render(
        request,
        "med_finance/charge_new.html",
        _context(
            organization_id,
            query=query,
            patients=patients,
            patient=patient,
            form=form,
            mode=mode,
            modes=modes,
            rows=rows,
            row_count=len(rows),
            can_add=len(rows) < finance_forms.MAX_ITEMS,
            item_errors=item_errors,
            idempotency_key=(request.POST.get("idempotency_key") or "")[:150] or uuid.uuid4().hex,
        ),
        status=status,
    )


def _typed(request: HttpRequest, prefix: str, names: Any) -> dict[str, str]:
    """What was typed in a form, as initial values: "Acrescentar item" shows it back without validating."""
    if request.method != "POST":
        return {}
    names = names or ("payer_name", "payer_document")
    return {name: request.POST[f"{prefix}{name}"] for name in names if f"{prefix}{name}" in request.POST}


def _item_row(request: HttpRequest, form_class: Any, index: int, prices: Any, *, bound: bool) -> Any:
    """One line of a new charge; a blank line is left out (``empty_permitted``), so no line is ``required``."""
    prefix = f"item-{index}"
    options = {"prefix": prefix, "prices": prices, "use_required_attribute": False}
    if bound:
        return form_class(request.POST, empty_permitted=True, **options)
    return form_class(initial=_typed(request, f"{prefix}-", tuple(form_class.base_fields)), **options)


@tenant_page()
def charge_view(
    request: HttpRequest, organization_id: UUID, charge_id: UUID, *, payment_form: Any = None, status: int = 200
) -> HttpResponse:
    try:
        detail = _service().charge(actor=request.user, charge_id=charge_id)
        payments = _service().payments(actor=request.user, charge_id=charge_id)
        receipts = _service().receipts(actor=request.user, charge_id=charge_id).items
    except (NotFound, Forbidden):
        raise Http404 from None
    charge = detail.charge
    receipt_of = {item.payment_id: item for item in receipts}
    panels = _rendered_panels(
        request,
        organization_id,
        _service().charge_panels(actor=request.user, charge_id=charge.sysid),
        charge_id=charge.sysid,
    )
    return render(
        request,
        "med_finance/charge.html",
        _context(
            organization_id,
            detail=detail,
            charge=charge,
            patient=_patients(request, [charge.patient_id]).get(charge.patient_id),
            payments=[{"payment": item, "receipt": receipt_of.get(item.sysid)} for item in payments],
            payment_form=payment_form
            or finance_forms.PaymentForm(initial={"amount": f"{charge.balance // 100},{charge.balance % 100:02d}"}),
            reason_form=finance_forms.ReasonForm(),
            idempotency_key=uuid.uuid4().hex,
            panels=panels,
        ),
        status=status,
    )


def _describe_charge_action(request: HttpRequest, organization_id: UUID, charge_id: UUID, action: str) -> Any:
    from django.urls import reverse

    if action != "cancel":
        return None
    try:
        charge = _service().charge(actor=request.user, charge_id=charge_id).charge
    except (NotFound, Forbidden):
        raise Http404 from None
    if charge.status in ("cancelled", "paid") or charge.balance != charge.total:
        raise Http404
    patient = _patients(request, [charge.patient_id]).get(charge.patient_id)
    return Confirmation(
        title=gettext("Cancelar a conta"),
        eyebrow=charge.code,
        subject=patient.display_name if patient else "",
        message=gettext("A conta deixa de cobrar o paciente e fica guardada como cancelada. Isso não se desfaz."),
        submit_label=gettext("Cancelar a conta"),
        cancel_url=reverse("med_finance:charge", args=(organization_id, charge_id)),
        hidden={"revision": charge.revision},
        reason_label=gettext("Motivo do cancelamento"),
        reason_required=True,
    )


@tenant_page()
@confirmation_step(_describe_charge_action)
@require_POST
def charge_action(request: HttpRequest, organization_id: UUID, charge_id: UUID, action: str) -> HttpResponse:
    revision = _revision(request)
    if action == "pay":
        form = finance_forms.PaymentForm(request.POST)
        received: list[Any] = []
        if form.is_valid() and _form_run(
            form,
            lambda: received.append(
                _service().register_payment(
                    actor=request.user,
                    charge_id=charge_id,
                    method=form.cleaned_data["method"],
                    amount=form.cleaned_data["amount"],
                    installments=form.cleaned_data["installments"],
                    authorization_code=form.cleaned_data["authorization_code"],
                    expected_revision=revision,
                    idempotency_key=_key(request),
                )
            ),
        ):
            messages.success(request, gettext("Pagamento recebido e recibo emitido."))
            # #132: straight to the receipt, whose first action is printing it.
            receipt = _receipt_of(request, charge_id, received[0].sysid)
            if receipt is not None:
                return redirect("med_finance:receipt", organization_id, receipt.sysid)
            return redirect("med_finance:charge", organization_id, charge_id)
        return charge_view(request, organization_id=organization_id, charge_id=charge_id, payment_form=form, status=400)
    elif action == "confirm":
        _run(
            request,
            lambda: _service().confirm_charge(actor=request.user, charge_id=charge_id, expected_revision=revision),
            gettext("Conta confirmada."),
        )
    elif action == "cancel":
        form = finance_forms.ReasonForm(request.POST)
        if form.is_valid():
            _run(
                request,
                lambda: _service().cancel_charge(
                    actor=request.user,
                    charge_id=charge_id,
                    reason=form.cleaned_data["reason"],
                    expected_revision=revision,
                ),
                gettext("Conta cancelada."),
            )
        else:
            messages.error(request, gettext("Informe o motivo."))
    else:
        raise Http404
    return redirect("med_finance:charge", organization_id, charge_id)


def _receipt_of(request: HttpRequest, charge_id: UUID, payment_id: UUID) -> Any:
    """The receipt issued for a payment of the charge, or ``None``."""
    try:
        receipts = _service().receipts(actor=request.user, charge_id=charge_id).items
    except (NotFound, Forbidden):
        return None
    return next((item for item in receipts if item.payment_id == payment_id), None)


def _payment_of(request: HttpRequest, charge_id: UUID, payment_id: UUID) -> Any:
    try:
        payments = _service().payments(actor=request.user, charge_id=charge_id)
    except (NotFound, Forbidden):
        raise Http404 from None
    payment = next((item for item in payments if item.sysid == payment_id), None)
    if payment is None or payment.status != "registered":
        raise Http404
    return payment


def _describe_reverse(request: HttpRequest, organization_id: UUID, payment_id: UUID) -> Confirmation:
    from django.urls import reverse

    from .templatetags.med_finance_format import brl, finance_label

    charge_id = _uuid(request.GET.get("charge", ""))
    payment = _payment_of(request, charge_id, payment_id)
    return Confirmation(
        title=gettext("Estornar o pagamento"),
        subject=f"{finance_label(payment.method, 'method')} · {brl(payment.amount)}",
        message=gettext("O valor volta a ficar em aberto na conta e sai do caixa em que foi recebido."),
        submit_label=gettext("Estornar o pagamento"),
        cancel_url=reverse("med_finance:charge", args=(organization_id, charge_id)),
        hidden={"revision": payment.revision, "charge": charge_id},
        reason_label=gettext("Motivo do estorno"),
        reason_required=True,
    )


@tenant_page()
@confirmation_step(_describe_reverse)
@require_POST
def payment_reverse(request: HttpRequest, organization_id: UUID, payment_id: UUID) -> HttpResponse:
    form = finance_forms.ReasonForm(request.POST)
    charge_id = _uuid(request.POST.get("charge", ""))
    if form.is_valid():
        _run(
            request,
            lambda: _service().reverse_payment(
                actor=request.user,
                payment_id=payment_id,
                reason=form.cleaned_data["reason"],
                expected_revision=_revision(request),
            ),
            gettext("Pagamento estornado."),
        )
    else:
        messages.error(request, gettext("Informe o motivo."))
    return redirect("med_finance:charge", organization_id, charge_id)


@require_POST
@tenant_page()
def collect(request: HttpRequest, organization_id: UUID, appointment_id: UUID) -> HttpResponse:
    """From an appointment ("Receber", a POST since #131): the charge of the appointment, created on first use.

    A GET answers 405 and creates nothing.
    """
    try:
        with transaction.atomic():
            detail = _service().charge_for_appointment(
                actor=request.user, appointment_id=appointment_id, idempotency_key=f"collect-{appointment_id}"
            )
    except (NotFound, Forbidden):
        raise Http404 from None
    except InvalidInput as error:
        messages.error(request, _errors(error))
        return redirect("med_scheduling:appointment", organization_id, appointment_id)
    except Conflict as error:
        messages.error(request, conflict_text(error))
        return redirect("med_scheduling:appointment", organization_id, appointment_id)
    return redirect("med_finance:charge", organization_id, detail.charge.sysid)


# ------------------------------------------------------------------------------------ receipts


def _receipt(request: HttpRequest, receipt_id: UUID) -> Any:
    try:
        return _service().receipt(actor=request.user, receipt_id=receipt_id)
    except (NotFound, Forbidden):
        raise Http404 from None


@tenant_page()
def receipt_view(request: HttpRequest, organization_id: UUID, receipt_id: UUID) -> HttpResponse:
    receipt = _receipt(request, receipt_id)
    panels = _rendered_panels(
        request,
        organization_id,
        _service().receipt_panels(actor=request.user, receipt_id=receipt.sysid),
        receipt_id=receipt.sysid,
    )
    return render(
        request,
        "med_finance/receipt.html",
        _context(
            organization_id,
            receipt=receipt,
            reason_form=finance_forms.ReasonForm(),
            idempotency_key=uuid.uuid4().hex,
            panels=panels,
        ),
    )


def _practice(request: HttpRequest) -> Any:
    """The clinic's identification for the printed receipt (address and phone), when the actor reads it."""
    from applications.med_scheduling.service_api import SchedulingService

    try:
        return SchedulingService().practice(actor=request.user)
    except (NotFound, Forbidden):
        return None


@tenant_page()
def receipt_print(request: HttpRequest, organization_id: UUID, receipt_id: UUID) -> HttpResponse:
    receipt = _receipt(request, receipt_id)
    return render(
        request,
        "med_finance/receipt_print.html",
        _context(organization_id, receipt=receipt, practice=_practice(request)),
    )


def _describe_void(request: HttpRequest, organization_id: UUID, receipt_id: UUID) -> Confirmation:
    from django.urls import reverse

    receipt = _receipt(request, receipt_id)
    if receipt.voided:
        raise Http404
    return Confirmation(
        title=gettext("Anular o recibo"),
        eyebrow=gettext("Recibo %(number)s") % {"number": receipt.number},
        message=gettext(
            "O recibo continua guardado, marcado como anulado, e o número não volta. "
            "Depois de anulado, o pagamento pode ser estornado."
        ),
        submit_label=gettext("Anular o recibo"),
        cancel_url=reverse("med_finance:receipt", args=(organization_id, receipt_id)),
        hidden={"idempotency_key": uuid.uuid4().hex},
        reason_label=gettext("Motivo da anulação"),
        reason_required=True,
    )


@tenant_page()
@confirmation_step(_describe_void)
@require_POST
def receipt_void(request: HttpRequest, organization_id: UUID, receipt_id: UUID) -> HttpResponse:
    form = finance_forms.ReasonForm(request.POST)
    if form.is_valid():
        _run(
            request,
            lambda: _service().void_receipt(
                actor=request.user,
                receipt_id=receipt_id,
                reason=form.cleaned_data["reason"],
                idempotency_key=_key(request),
            ),
            gettext("Recibo anulado."),
        )
    else:
        messages.error(request, gettext("Informe o motivo."))
    return redirect("med_finance:receipt", organization_id, receipt_id)


# ------------------------------------------------------------------------------------ prices, patient, setup


@tenant_page()
def prices_view(request: HttpRequest, organization_id: UUID) -> HttpResponse:
    try:
        lists = _service().price_lists(actor=request.user)
        items = _service().price_items(actor=request.user, active_only=False)
    except (NotFound, Forbidden):
        raise Http404 from None
    writable = bool(lists and lists[0].writable)
    form = finance_forms.PriceForm(request.POST or None)
    status = 200
    if request.method == "POST":
        if not writable:
            raise Http404
        status = 400
        if form.is_valid():
            try:
                with transaction.atomic():
                    _service().add_price_item(
                        actor=request.user,
                        code=form.cleaned_data["code"],
                        description=form.cleaned_data["description"],
                        amount=form.cleaned_data["amount"],
                        idempotency_key=_key(request),
                    )
            except (NotFound, Forbidden):
                raise Http404 from None
            except InvalidInput as error:
                finance_forms.apply_service_errors(form, error)
            except Conflict as error:
                form.add_error(None, conflict_text(error))
            else:
                messages.success(request, gettext("Item incluído."))
                return redirect("med_finance:prices", organization_id)
    return render(
        request,
        "med_finance/prices.html",
        _context(organization_id, items=items, writable=writable, form=form, idempotency_key=uuid.uuid4().hex),
        status=status,
    )


def _describe_price_deactivate(request: HttpRequest, organization_id: UUID, item_id: UUID) -> Confirmation:
    from django.urls import reverse

    from .templatetags.med_finance_format import brl

    try:
        lists = _service().price_lists(actor=request.user)
        items = _service().price_items(actor=request.user, active_only=True)
    except (NotFound, Forbidden):
        raise Http404 from None
    item = next((row for row in items if row.sysid == item_id), None)
    if item is None or not (lists and lists[0].writable):
        raise Http404
    return Confirmation(
        title=gettext("Desativar o item"),
        subject=f"{item.code} · {item.description} · {brl(item.amount)}",
        message=gettext("O item deixa de entrar em contas novas. As contas que já o têm não mudam."),
        submit_label=gettext("Desativar o item"),
        cancel_url=reverse("med_finance:prices", args=(organization_id,)),
        hidden={"revision": item.revision},
    )


@tenant_page()
@confirmation_step(_describe_price_deactivate)
@require_POST
def price_deactivate(request: HttpRequest, organization_id: UUID, item_id: UUID) -> HttpResponse:
    _describe_price_deactivate(request, organization_id, item_id)
    _run(
        request,
        lambda: _service().update_price_item(
            actor=request.user, item_id=item_id, changes=(("is_active", False),), expected_revision=_revision(request)
        ),
        gettext("Item desativado."),
    )
    return redirect("med_finance:prices", organization_id)


@tenant_page()
def patient_section(request: HttpRequest, organization_id: UUID, patient_id: UUID) -> HttpResponse:
    """The "Financeiro" tab of the patient page."""
    from django.urls import NoReverseMatch, reverse

    if not _service().desks(actor=request.user):
        raise Http404
    try:
        patient = PatientService().summary(actor=request.user, patient_id=patient_id)
        tabs = PatientService().page_tabs(actor=request.user, patient_id=patient_id)
    except (NotFound, Forbidden):
        raise Http404 from None
    navigation = []
    for tab in tabs:
        try:
            url = reverse(tab.url_name, args=(organization_id, patient_id))
        except NoReverseMatch:
            continue
        navigation.append({"label": tab.label, "url": url, "current": tab.code == "med_finance.account"})
    return render(
        request,
        "med_finance/patient_section.html",
        _context(
            organization_id,
            patient=patient,
            tabs=navigation,
            charges=_service().charges(actor=request.user, patient_id=patient_id, page_size=100).items,
            balance=_service().patient_balance(actor=request.user, patient_id=patient_id),
        ),
    )


@tenant_page()
def setup_view(request: HttpRequest, organization_id: UUID) -> HttpResponse:
    from skeleton.service_api.access import AccessService
    from skeleton.service_api.organizations import OrganizationService

    if "access.manage" not in AccessService().capabilities(actor=request.user):
        raise Http404
    groups = OrganizationService().groups(actor=request.user, page_size=100).items
    form = finance_forms.SetupForm(request.POST or None, groups=groups)
    status = 200
    if request.method == "POST":
        status = 400
        if form.is_valid():
            values = form.cleaned_data
            try:
                with transaction.atomic():
                    _service().setup(
                        actor=request.user,
                        desk_name=values["desk_name"],
                        price_list_name=values["price_list_name"],
                        writer_group_ids=tuple(UUID(value) for value in values["writer_groups"]),
                        reader_group_ids=tuple(UUID(value) for value in values["reader_groups"]),
                        price_manager_group_ids=tuple(UUID(value) for value in values["price_manager_groups"]),
                        idempotency_key=f"page-setup-{organization_id}",
                    )
            except (NotFound, Forbidden):
                raise Http404 from None
            except InvalidInput as error:
                finance_forms.apply_service_errors(form, error)
            except Conflict as error:
                form.add_error(None, conflict_text(error))
            else:
                messages.success(request, gettext("Financeiro configurado."))
                return redirect("med_finance:desk", organization_id)
    return render(request, "med_finance/setup.html", _context(organization_id, form=form), status=status)


# ------------------------------------------------------------------------------------ reports


@tenant_page()
def daily_view(request: HttpRequest, organization_id: UUID) -> HttpResponse:
    """One day of the desks, with the day before and the day after (#132); printed without the navigation."""
    from datetime import timedelta

    from django.utils import timezone

    day = _query_date(request, "date") or timezone.localdate()
    if not _service().desks(actor=request.user):
        raise Http404
    summary = _service().daily_summary(actor=request.user, date=day)
    return render(
        request,
        "med_finance/daily.html",
        _context(
            organization_id,
            summary=summary,
            previous_day=day - timedelta(days=1),
            next_day=day + timedelta(days=1),
            today=timezone.localdate(),
        ),
    )


@tenant_page()
def receivables_view(request: HttpRequest, organization_id: UUID) -> HttpResponse:
    """The receivables by days overdue; each bucket links to its charges on the charges page (#132)."""
    if not _service().desks(actor=request.user):
        raise Http404
    report = _service().receivables(actor=request.user)
    buckets = [
        {
            "bucket": item,
            "query": _charges_query(status=OUTSTANDING, due_from=item.due_from, due_to=item.due_to),
        }
        for item in report.buckets
    ]
    return render(request, "med_finance/receivables.html", _context(organization_id, report=report, buckets=buckets))
