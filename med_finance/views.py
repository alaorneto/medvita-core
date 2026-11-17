"""Pages of the finance app: every read and write goes through FinanceService (and the other apps' services).

Amounts are typed in reais and shown with the ``brl`` filter; the service keeps integer centavos.
A desk, charge or receipt the actor cannot read answers 404.
"""

from __future__ import annotations

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
from skeleton.web.views import tenant_page

from . import forms as finance_forms
from .service_api import ChargeItemInput, FinanceService


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


# ------------------------------------------------------------------------------------ desk


@tenant_page()
def desk_view(request: HttpRequest, organization_id: UUID) -> HttpResponse:
    """The cash desk of the day: the session, its totals and movements, and the open charges."""
    from skeleton.service_api.access import AccessService

    desks = _service().desks(actor=request.user)
    if not desks:
        manager = "access.manage" in AccessService().capabilities(actor=request.user)
        return render(request, "med_finance/empty.html", _context(organization_id, manager=manager))
    desk = desks[0]
    session = _service().current_session(actor=request.user, desk_id=desk.sysid)
    report = _service().session_report(actor=request.user, session_id=session.sysid) if session else None
    charges = _service().charges(actor=request.user, desk_id=desk.sysid, page_size=30).items
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
            open_form=finance_forms.OpenSessionForm(),
            movement_form=finance_forms.MovementForm(),
            close_form=finance_forms.CloseSessionForm(),
            idempotency_key=uuid.uuid4().hex,
        ),
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
    if form.is_valid():
        _run(
            request,
            lambda: _service().add_movement(
                actor=request.user,
                session_id=session_id,
                kind=form.cleaned_data["kind"],
                amount=form.cleaned_data["amount"],
                reason=form.cleaned_data["reason"],
                idempotency_key=_key(request),
            ),
            gettext("Movimento registrado."),
        )
    else:
        messages.error(request, " ".join(str(error) for errors in form.errors.values() for error in errors))
    return redirect("med_finance:desk", organization_id)


@require_POST
@tenant_page()
def session_close(request: HttpRequest, organization_id: UUID, session_id: UUID) -> HttpResponse:
    form = finance_forms.CloseSessionForm(request.POST)
    if form.is_valid() and _run(
        request,
        lambda: _service().close_session(
            actor=request.user,
            session_id=session_id,
            counted_amount=form.cleaned_data["counted_amount"],
            note=form.cleaned_data["note"],
            expected_revision=_revision(request),
        ),
        gettext("Caixa fechado."),
    ):
        return redirect("med_finance:session", organization_id, session_id)
    if not form.is_valid():
        messages.error(request, " ".join(str(error) for errors in form.errors.values() for error in errors))
    return redirect("med_finance:desk", organization_id)


@tenant_page()
def session_view(request: HttpRequest, organization_id: UUID, session_id: UUID) -> HttpResponse:
    try:
        report = _service().session_report(actor=request.user, session_id=session_id)
    except (NotFound, Forbidden):
        raise Http404 from None
    return render(request, "med_finance/session.html", _context(organization_id, report=report))


# ------------------------------------------------------------------------------------ charges


@tenant_page()
def charges_view(request: HttpRequest, organization_id: UUID) -> HttpResponse:
    status = request.GET.get("status") or None
    try:
        page = _service().charges(
            actor=request.user, status=status, cursor=request.GET.get("cursor") or None, page_size=50
        )
    except InvalidInput:
        raise Http404 from None
    names = _patients(request, [item.patient_id for item in page.items])
    return render(
        request,
        "med_finance/charges.html",
        _context(
            organization_id,
            page=page,
            status=status or "",
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
    form = finance_forms.ChargeForm(request.POST or None, prices=prices)
    status = 200
    if request.method == "POST" and patient is not None:
        status = 400
        if form.is_valid():
            values = form.cleaned_data
            item = ChargeItemInput(
                code=values["code"],
                description=values["description"],
                quantity=values["quantity"],
                unit_amount=values["unit_amount"] if not values["code"] else None,
                discount_amount=values["discount_amount"] or 0,
            )
            try:
                with transaction.atomic():
                    detail = _service().create_charge(
                        actor=request.user,
                        patient_id=patient.sysid,
                        items=(item,),
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
    return render(
        request,
        "med_finance/charge_new.html",
        _context(
            organization_id,
            query=query,
            patients=patients,
            patient=patient,
            form=form,
            idempotency_key=uuid.uuid4().hex,
        ),
        status=status,
    )


@tenant_page()
def charge_view(request: HttpRequest, organization_id: UUID, charge_id: UUID) -> HttpResponse:
    try:
        detail = _service().charge(actor=request.user, charge_id=charge_id)
        payments = _service().payments(actor=request.user, charge_id=charge_id)
        receipts = _service().receipts(actor=request.user, charge_id=charge_id).items
    except (NotFound, Forbidden):
        raise Http404 from None
    charge = detail.charge
    receipt_of = {item.payment_id: item for item in receipts}
    return render(
        request,
        "med_finance/charge.html",
        _context(
            organization_id,
            detail=detail,
            charge=charge,
            patient=_patients(request, [charge.patient_id]).get(charge.patient_id),
            payments=[{"payment": item, "receipt": receipt_of.get(item.sysid)} for item in payments],
            payment_form=finance_forms.PaymentForm(
                initial={"amount": f"{charge.balance // 100},{charge.balance % 100:02d}"}
            ),
            reason_form=finance_forms.ReasonForm(),
            idempotency_key=uuid.uuid4().hex,
        ),
    )


@require_POST
@tenant_page()
def charge_action(request: HttpRequest, organization_id: UUID, charge_id: UUID, action: str) -> HttpResponse:
    revision = _revision(request)
    if action == "pay":
        form = finance_forms.PaymentForm(request.POST)
        if not form.is_valid():
            messages.error(request, " ".join(str(error) for errors in form.errors.values() for error in errors))
            return redirect("med_finance:charge", organization_id, charge_id)
        values = form.cleaned_data
        _run(
            request,
            lambda: _service().register_payment(
                actor=request.user,
                charge_id=charge_id,
                method=values["method"],
                amount=values["amount"],
                installments=values["installments"],
                authorization_code=values["authorization_code"],
                expected_revision=revision,
                idempotency_key=_key(request),
            ),
            gettext("Pagamento recebido e recibo emitido."),
        )
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


@require_POST
@tenant_page()
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


@tenant_page()
def collect(request: HttpRequest, organization_id: UUID, appointment_id: UUID) -> HttpResponse:
    """From an appointment: the charge of the appointment (created on first use)."""
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
    return render(
        request,
        "med_finance/receipt.html",
        _context(
            organization_id, receipt=receipt, reason_form=finance_forms.ReasonForm(), idempotency_key=uuid.uuid4().hex
        ),
    )


@tenant_page()
def receipt_print(request: HttpRequest, organization_id: UUID, receipt_id: UUID) -> HttpResponse:
    return render(
        request, "med_finance/receipt_print.html", _context(organization_id, receipt=_receipt(request, receipt_id))
    )


@require_POST
@tenant_page()
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
        if request.POST.get("action") == "deactivate":
            if _run(
                request,
                lambda: _service().update_price_item(
                    actor=request.user,
                    item_id=_uuid(request.POST.get("id", "")),
                    changes=(("is_active", False),),
                    expected_revision=_revision(request),
                ),
                gettext("Item desativado."),
            ):
                return redirect("med_finance:prices", organization_id)
        elif form.is_valid():
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
