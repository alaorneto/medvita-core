"""Pages and REST API of the patients app: every read and write goes through PatientService.

An unreadable or foreign patient answers 404 (the service says NotFound); a write without the
right answers 403 on the API and a message on the pages; a stale revision comes back as a
readable message. Validation errors are put on the form fields; they never echo the value.
"""

from __future__ import annotations

import uuid
from datetime import date
from typing import Any
from uuid import UUID

from django.contrib import messages
from django.db import transaction
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.urls import NoReverseMatch, reverse
from django.utils import timezone
from django.utils.translation import gettext
from django.views.decorators.http import require_POST
from rest_framework.response import Response

from skeleton.api.views import TenantAPI, request_fields
from skeleton.service_api import Conflict, Forbidden, InvalidInput, NotFound
from skeleton.web.views import tenant_page

from . import forms as patient_forms
from .models import Patient
from .service_api import CoverageInput, GuardianInput, PatientInput, PatientService

PAGE_SIZE = 25
INPUT_FIELDS = tuple(PatientInput.__dataclass_fields__)


def _service() -> PatientService:
    return PatientService()


def conflict_text(error: Conflict) -> str:
    texts = {
        "stale_revision": gettext("O cadastro mudou desde que a página abriu. Atualize a página e tente de novo."),
        "integrity_conflict": gettext("Já existe um paciente vivo com este CPF."),
        "processing_restricted": gettext("O tratamento dos dados deste paciente está restrito: o cadastro não muda."),
        "anonymized": gettext("Paciente anonimizado: o cadastro é somente leitura."),
        "already_granted": gettext("Já existe um consentimento vigente para esta finalidade."),
        "already_revoked": gettext("Este consentimento já foi revogado."),
        "already_set_up": gettext("A organização já tem um cadastro de pacientes."),
        "retention": gettext("A guarda legal impede excluir este paciente."),
        "live_references": gettext("O paciente ainda é usado por outra app e não pode ser excluído."),
        "import_state": gettext("A importação já está em outra etapa."),
    }
    return texts.get(error.code, gettext("A operação conflita com o estado atual."))


def _messages_of(error: InvalidInput) -> str:
    return " ".join(text for texts in error.errors.values() for text in texts)


def _revision(request: HttpRequest) -> int:
    try:
        return int(request.POST.get("revision", ""))
    except ValueError:
        return 0


def _key(request: HttpRequest) -> str:
    return (request.POST.get("idempotency_key") or "")[:150] or uuid.uuid4().hex


def _age(born: date | None) -> int | None:
    if born is None:
        return None
    today = timezone.localdate()
    return today.year - born.year - ((today.month, today.day) < (born.month, born.day))


def _bad_request(request: HttpRequest, organization_id: UUID, detail: str) -> HttpResponse:
    return render(
        request, "med_patients/bad_request.html", {"organization_id": organization_id, "detail": detail}, status=400
    )


def _patient_or_404(request: HttpRequest, patient_id: UUID) -> Any:
    try:
        return _service().get(actor=request.user, patient_id=patient_id)
    except (NotFound, Forbidden, InvalidInput):
        raise Http404 from None


def _tabs(request: HttpRequest, organization_id: UUID, patient: Any, active: str) -> list[dict[str, Any]]:
    tabs = []
    for tab in _service().page_tabs(actor=request.user, patient_id=patient.sysid):
        try:
            url = reverse(tab.url_name, args=(organization_id, patient.sysid))
        except NoReverseMatch:
            continue
        tabs.append({"code": tab.code, "label": tab.label, "url": url, "current": tab.code == active})
    return tabs


def patient_context(request: HttpRequest, organization_id: UUID, patient: Any, active: str) -> dict[str, Any]:
    """Header and tabs of a patient page; other apps' sections render their tab with it too."""
    return {
        "organization_id": organization_id,
        "patient": patient,
        "age": _age(patient.birth_date),
        "tabs": _tabs(request, organization_id, patient, active),
    }


def _input(data: dict[str, Any]) -> PatientInput:
    values = {name: ("" if value is None else value) for name, value in data.items() if name != "birth_date"}
    return PatientInput(**values, birth_date=data.get("birth_date"))


# ------------------------------------------------------------------------------------- pages


@tenant_page()
def patient_list(request: HttpRequest, organization_id: UUID) -> HttpResponse:
    query = request.GET.get("q", "")[:200]
    status = request.GET.get("status") or None
    try:
        registries = _service().registries(actor=request.user)
        page = _service().search(
            actor=request.user,
            query=query,
            status=status,
            cursor=request.GET.get("cursor") or None,
            page_size=PAGE_SIZE,
        )
    except InvalidInput:
        return _bad_request(request, organization_id, gettext("Filtro ou página inválida."))
    except (Forbidden, NotFound):
        raise Http404 from None
    return render(
        request,
        "med_patients/list.html",
        {
            "organization_id": organization_id,
            "page": page,
            "query": query,
            "status": status or "",
            "statuses": Patient.Status.choices,
            "can_create": any(registry.writable for registry in registries),
            "has_registry": bool(registries),
        },
    )


@tenant_page()
def patient_create(request: HttpRequest, organization_id: UUID) -> HttpResponse:
    form = patient_forms.PatientForm(request.POST or None)
    duplicates: tuple[Any, ...] = ()
    status = 200
    if request.method == "POST":
        status = 400
        if form.is_valid():
            data = form.cleaned_data
            try:
                if not request.POST.get("confirm_duplicates"):
                    duplicates = _service().find_duplicates(
                        actor=request.user, cpf=data["cpf"], full_name=data["full_name"], birth_date=data["birth_date"]
                    )
                if duplicates:
                    status = 200
                else:
                    with transaction.atomic():
                        patient = _service().create(
                            actor=request.user, data=_input(data), idempotency_key=_key(request)
                        )
                    messages.success(request, gettext("Paciente cadastrado."))
                    return redirect("med_patients:detail", organization_id, patient.sysid)
            except (Forbidden, NotFound):
                raise Http404 from None
            except InvalidInput as error:
                patient_forms.apply_service_errors(form, error)
            except Conflict as error:
                form.add_error(None, conflict_text(error))
    return render(
        request,
        "med_patients/form.html",
        {
            "organization_id": organization_id,
            "form": form,
            "duplicates": duplicates,
            "heading": gettext("Novo paciente"),
            "idempotency_key": _key(request),
        },
        status=status,
    )


@tenant_page()
def patient_detail(request: HttpRequest, organization_id: UUID, patient_id: UUID) -> HttpResponse:
    patient = _patient_or_404(request, patient_id)
    context = patient_context(request, organization_id, patient, "detail")
    context["status_form"] = patient_forms.StatusForm(
        initial={"status": patient.status, "deceased_on": patient.deceased_on}
    )
    return render(request, "med_patients/detail.html", context)


@tenant_page()
def patient_edit(request: HttpRequest, organization_id: UUID, patient_id: UUID) -> HttpResponse:
    patient = _patient_or_404(request, patient_id)
    if not patient.writable:
        raise Http404
    initial = {name: getattr(patient, name) for name in patient_forms.PatientForm.base_fields}
    form = patient_forms.PatientForm(request.POST or None, initial=initial)
    status = 200
    if request.method == "POST":
        status = 400
        if form.is_valid():
            # The service compares after normalizing and writes only what really changed.
            changes = tuple(
                (name, value if value is not None or name == "birth_date" else "")
                for name, value in form.cleaned_data.items()
            )
            try:
                with transaction.atomic():
                    _service().update(
                        actor=request.user, patient_id=patient_id, changes=changes, expected_revision=_revision(request)
                    )
            except (Forbidden, NotFound):
                raise Http404 from None
            except InvalidInput as error:
                patient_forms.apply_service_errors(form, error)
            except Conflict as error:
                form.add_error(None, conflict_text(error))
            else:
                messages.success(request, gettext("Cadastro atualizado."))
                return redirect("med_patients:detail", organization_id, patient_id)
    return render(
        request,
        "med_patients/form.html",
        {"organization_id": organization_id, "form": form, "patient": patient, "heading": gettext("Alterar cadastro")},
        status=status,
    )


@require_POST
@tenant_page()
def patient_status(request: HttpRequest, organization_id: UUID, patient_id: UUID) -> HttpResponse:
    form = patient_forms.StatusForm(request.POST)
    if not form.is_valid():
        messages.error(request, gettext("Escolha uma situação válida."))
        return redirect("med_patients:detail", organization_id, patient_id)
    try:
        with transaction.atomic():
            _service().set_status(
                actor=request.user,
                patient_id=patient_id,
                status=form.cleaned_data["status"],
                deceased_on=form.cleaned_data["deceased_on"],
                expected_revision=_revision(request),
            )
    except (Forbidden, NotFound):
        raise Http404 from None
    except InvalidInput as error:
        messages.error(request, _messages_of(error))
    except Conflict as error:
        messages.error(request, conflict_text(error))
    else:
        messages.success(request, gettext("Situação atualizada."))
    return redirect("med_patients:detail", organization_id, patient_id)


def _child_page(
    request: HttpRequest,
    organization_id: UUID,
    patient_id: UUID,
    *,
    tab: str,
    form: Any,
    add: Any,
    done: str,
    rows: Any,
    template: str,
    extra: dict[str, Any] | None = None,
) -> HttpResponse:
    """The pattern of the guardians, coverages and consents tabs: a list and an add form."""
    patient = _patient_or_404(request, patient_id)
    status = 200
    if request.method == "POST":
        status = 400
        if form.is_valid():
            try:
                with transaction.atomic():
                    add(form.cleaned_data)
            except (Forbidden, NotFound):
                raise Http404 from None
            except InvalidInput as error:
                patient_forms.apply_service_errors(form, error)
            except Conflict as error:
                form.add_error(None, conflict_text(error))
            else:
                messages.success(request, done)
                return redirect(f"med_patients:{tab}", organization_id, patient_id)
    context = patient_context(request, organization_id, patient, tab)
    context.update({"rows": rows(), "form": form, "idempotency_key": _key(request), **(extra or {})})
    return render(request, template, context, status=status)


@tenant_page()
def patient_guardians(request: HttpRequest, organization_id: UUID, patient_id: UUID) -> HttpResponse:
    def add(data: dict[str, Any]) -> Any:
        return _service().add_guardian(
            actor=request.user, patient_id=patient_id, data=GuardianInput(**data), idempotency_key=_key(request)
        )

    return _child_page(
        request,
        organization_id,
        patient_id,
        tab="guardians",
        form=patient_forms.GuardianForm(request.POST or None),
        add=add,
        done=gettext("Responsável incluído."),
        rows=lambda: _service().guardians(actor=request.user, patient_id=patient_id),
        template="med_patients/guardians.html",
    )


@tenant_page()
def patient_coverages(request: HttpRequest, organization_id: UUID, patient_id: UUID) -> HttpResponse:
    def add(data: dict[str, Any]) -> Any:
        return _service().add_coverage(
            actor=request.user, patient_id=patient_id, data=CoverageInput(**data), idempotency_key=_key(request)
        )

    return _child_page(
        request,
        organization_id,
        patient_id,
        tab="coverages",
        form=patient_forms.CoverageForm(request.POST or None),
        add=add,
        done=gettext("Convênio incluído."),
        rows=lambda: _service().coverages(actor=request.user, patient_id=patient_id),
        template="med_patients/coverages.html",
    )


@tenant_page()
def patient_consents(request: HttpRequest, organization_id: UUID, patient_id: UUID) -> HttpResponse:
    from skeleton.service_api.files import FileService

    purposes = _service().consent_purposes(actor=request.user)

    def add(data: dict[str, Any]) -> Any:
        return _service().grant_consent(
            actor=request.user, patient_id=patient_id, idempotency_key=_key(request), **data
        )

    def rows() -> list[dict[str, Any]]:
        files = FileService()
        return [
            {
                "consent": consent,
                "attachments": files.list(
                    actor=request.user, table_key="med_patients.consent", record_id=consent.sysid
                ).items,
            }
            for consent in _service().consents(actor=request.user, patient_id=patient_id)
        ]

    return _child_page(
        request,
        organization_id,
        patient_id,
        tab="consents",
        form=patient_forms.ConsentForm(request.POST or None, purposes=purposes),
        add=add,
        done=gettext("Consentimento registrado."),
        rows=rows,
        template="med_patients/consents.html",
        extra={"labels": {purpose.code: purpose.label for purpose in purposes}, "term_form": patient_forms.TermForm()},
    )


def _remove(
    request: HttpRequest, organization_id: UUID, patient_id: UUID, *, tab: str, call: Any, done: str
) -> HttpResponse:
    try:
        with transaction.atomic():
            call()
    except (Forbidden, NotFound):
        raise Http404 from None
    except Conflict as error:
        messages.error(request, conflict_text(error))
    else:
        messages.success(request, done)
    return redirect(f"med_patients:{tab}", organization_id, patient_id)


@require_POST
@tenant_page()
def guardian_remove(request: HttpRequest, organization_id: UUID, patient_id: UUID, row_id: UUID) -> HttpResponse:
    return _remove(
        request,
        organization_id,
        patient_id,
        tab="guardians",
        call=lambda: _service().remove_guardian(
            actor=request.user, guardian_id=row_id, expected_revision=_revision(request)
        ),
        done=gettext("Responsável removido."),
    )


@require_POST
@tenant_page()
def coverage_remove(request: HttpRequest, organization_id: UUID, patient_id: UUID, row_id: UUID) -> HttpResponse:
    return _remove(
        request,
        organization_id,
        patient_id,
        tab="coverages",
        call=lambda: _service().remove_coverage(
            actor=request.user, coverage_id=row_id, expected_revision=_revision(request)
        ),
        done=gettext("Convênio removido."),
    )


@require_POST
@tenant_page()
def consent_revoke(request: HttpRequest, organization_id: UUID, patient_id: UUID, row_id: UUID) -> HttpResponse:
    return _remove(
        request,
        organization_id,
        patient_id,
        tab="consents",
        call=lambda: _service().revoke_consent(
            actor=request.user, consent_id=row_id, expected_revision=_revision(request)
        ),
        done=gettext("Consentimento revogado."),
    )


@require_POST
@tenant_page()
def consent_term(request: HttpRequest, organization_id: UUID, patient_id: UUID, row_id: UUID) -> HttpResponse:
    from skeleton.service_api.files import FileService

    form = patient_forms.TermForm(request.POST, request.FILES)
    if not form.is_valid():
        messages.error(request, gettext("Escolha o arquivo do termo."))
        return redirect("med_patients:consents", organization_id, patient_id)
    upload = form.cleaned_data["term"]
    extension = upload.name.rsplit(".", 1)[-1].lower()[:5] if "." in upload.name else "pdf"
    try:
        with transaction.atomic():
            # A fixed name: the original file name may carry the patient's name.
            FileService().attach(
                actor=request.user,
                table_key="med_patients.consent",
                record_id=row_id,
                filename=f"termo-de-consentimento.{extension}",
                stream=upload,
                content_type=upload.content_type,
            )
    except (Forbidden, NotFound):
        raise Http404 from None
    except InvalidInput as error:
        messages.error(request, _messages_of(error))
    else:
        messages.success(request, gettext("Termo anexado."))
    return redirect("med_patients:consents", organization_id, patient_id)


@tenant_page()
def attachment_download(request: HttpRequest, organization_id: UUID, attachment_id: UUID) -> HttpResponse:
    from skeleton.service_api.files import FileService

    try:
        return redirect(FileService().download_url(actor=request.user, attachment_id=attachment_id))
    except (Forbidden, NotFound, InvalidInput):
        raise Http404 from None


@tenant_page()
def patient_timeline(request: HttpRequest, organization_id: UUID, patient_id: UUID) -> HttpResponse:
    patient = _patient_or_404(request, patient_id)
    try:
        page = _service().timeline(actor=request.user, patient_id=patient_id, cursor=request.GET.get("cursor") or None)
    except InvalidInput:
        return _bad_request(request, organization_id, gettext("Página inválida."))
    entries = []
    for entry in page.items:
        url = ""
        if entry.url_name:
            try:
                url = reverse(entry.url_name, args=(organization_id, *entry.url_args))
            except NoReverseMatch:
                url = ""
        entries.append({"entry": entry, "url": url})
    context = patient_context(request, organization_id, patient, "timeline")
    context.update({"entries": entries, "page": page})
    return render(request, "med_patients/timeline.html", context)


@tenant_page()
def registry_setup(request: HttpRequest, organization_id: UUID) -> HttpResponse:
    from skeleton.service_api.access import AccessService
    from skeleton.service_api.organizations import OrganizationService

    if "access.manage" not in AccessService().capabilities(actor=request.user):
        raise Http404
    groups = OrganizationService().groups(actor=request.user, page_size=100).items
    form = patient_forms.SetupForm(request.POST or None, groups=groups)
    status = 200
    if request.method == "POST":
        status = 400
        if form.is_valid():
            data = form.cleaned_data
            try:
                with transaction.atomic():
                    _service().setup(
                        actor=request.user,
                        name=data["name"],
                        writer_group_ids=tuple(UUID(value) for value in data["writer_groups"]),
                        reader_group_ids=tuple(UUID(value) for value in data["reader_groups"]),
                        idempotency_key=f"page-setup-{organization_id}",
                    )
            except (Forbidden, NotFound):
                raise Http404 from None
            except InvalidInput as error:
                patient_forms.apply_service_errors(form, error)
            except Conflict as error:
                form.add_error(None, conflict_text(error))
            else:
                messages.success(request, gettext("Cadastro de pacientes configurado."))
                return redirect("med_patients:list", organization_id)
    return render(request, "med_patients/setup.html", {"organization_id": organization_id, "form": form}, status=status)


# --------------------------------------------------------------------------------------- API


def _json(value: Any) -> Any:
    if isinstance(value, UUID):
        return str(value)
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value


def _dto_json(item: Any) -> dict[str, Any]:
    return {name: _json(getattr(item, name)) for name in item.__dataclass_fields__}


def _if_match(request: Any) -> int:
    header = request.headers.get("If-Match", "").strip().removeprefix("W/")
    try:
        return int(header.strip('"'))
    except ValueError:
        raise InvalidInput({"If-Match": [gettext("Envie a revisão atual no cabeçalho If-Match.")]}) from None


def _with_etag(response: Response, revision: int) -> Response:
    response["ETag"] = f'"{revision}"'
    return response


def _api_fields(request: Any) -> dict[str, Any]:
    fields = request_fields(request)
    unknown = sorted(set(fields) - set(INPUT_FIELDS))
    if unknown:
        raise InvalidInput({name: [gettext("Campo não aceito.")] for name in unknown})
    if fields.get("birth_date"):
        try:
            fields["birth_date"] = date.fromisoformat(str(fields["birth_date"]))
        except ValueError:
            raise InvalidInput({"birth_date": [gettext("Use uma data válida (AAAA-MM-DD).")]}) from None
    return fields


class PatientsAPI(TenantAPI):
    def get(self, request, organization_id):
        size = request.query_params.get("page_size", "")
        page = _service().search(
            actor=request.user,
            query=request.query_params.get("q", "")[:200],
            status=request.query_params.get("status") or None,
            cursor=request.query_params.get("cursor") or None,
            page_size=int(size) if size.isdigit() else PAGE_SIZE,
        )
        return Response({"results": [_dto_json(item) for item in page.items], "next_cursor": page.next_cursor})

    def post(self, request, organization_id):
        fields = _api_fields(request)
        if not fields.get("full_name"):
            raise InvalidInput({"full_name": [gettext("Informe o nome completo.")]})
        with transaction.atomic():
            info = _service().create(
                actor=request.user,
                data=_input(fields),
                idempotency_key=request.headers.get("Idempotency-Key") or None,
            )
        return _with_etag(Response(_dto_json(info), status=201), info.revision)


class PatientAPI(TenantAPI):
    def get(self, request, organization_id, patient_id):
        info = _service().get(actor=request.user, patient_id=patient_id)
        return _with_etag(Response(_dto_json(info)), info.revision)

    def patch(self, request, organization_id, patient_id):
        revision = _if_match(request)
        fields = _api_fields(request)
        with transaction.atomic():
            info = _service().update(
                actor=request.user, patient_id=patient_id, changes=tuple(fields.items()), expected_revision=revision
            )
        return _with_etag(Response(_dto_json(info)), info.revision)


class GuardiansAPI(TenantAPI):
    def get(self, request, organization_id, patient_id):
        rows = _service().guardians(actor=request.user, patient_id=patient_id)
        return Response({"results": [_dto_json(row) for row in rows]})


class CoveragesAPI(TenantAPI):
    def get(self, request, organization_id, patient_id):
        rows = _service().coverages(actor=request.user, patient_id=patient_id)
        return Response({"results": [_dto_json(row) for row in rows]})


# ------------------------------------------------------------------------------------ import

IMPORT_FIELDS = (
    ("full_name", gettext("Nome completo")),
    ("social_name", gettext("Nome social")),
    ("birth_date", gettext("Data de nascimento (AAAA-MM-DD)")),
    ("sex", gettext("Sexo")),
    ("cpf", gettext("CPF")),
    ("national_health_card", gettext("Cartão Nacional de Saúde")),
    ("identity_document", gettext("Documento de identidade")),
    ("mother_name", gettext("Nome da mãe")),
    ("phone", gettext("Telefone")),
    ("phone_secondary", gettext("Outro telefone")),
    ("email", gettext("Email")),
    ("postal_code", gettext("CEP")),
    ("street", gettext("Logradouro")),
    ("number", gettext("Número")),
    ("complement", gettext("Complemento")),
    ("district", gettext("Bairro")),
    ("city", gettext("Cidade")),
    ("state", gettext("UF")),
    ("notes", gettext("Observações")),
)


@tenant_page()
def imports(request: HttpRequest, organization_id: UUID) -> HttpResponse:
    form = patient_forms.ImportUploadForm(request.POST or None, request.FILES or None)
    status = 200
    if request.method == "POST":
        status = 400
        if form.is_valid():
            try:
                with transaction.atomic():
                    batch = _service().start_import(
                        actor=request.user, stream=form.cleaned_data["file"], idempotency_key=_key(request)
                    )
            except (Forbidden, NotFound):
                raise Http404 from None
            except InvalidInput as error:
                patient_forms.apply_service_errors(form, error)
            else:
                return redirect("med_patients:import", organization_id, batch.sysid)
    try:
        rows = _service().imports(actor=request.user)
    except (Forbidden, NotFound):
        raise Http404 from None
    return render(
        request,
        "med_patients/imports.html",
        {"organization_id": organization_id, "form": form, "rows": rows, "idempotency_key": _key(request)},
        status=status,
    )


@tenant_page()
def import_detail(request: HttpRequest, organization_id: UUID, batch_id: UUID) -> HttpResponse:
    try:
        batch = _service().import_status(actor=request.user, batch_id=batch_id)
    except (Forbidden, NotFound, InvalidInput):
        raise Http404 from None
    form = patient_forms.ImportMappingForm(
        request.POST or None, columns=batch.columns, mapping=dict(batch.mapping), fields=IMPORT_FIELDS
    )
    status = 200
    if request.method == "POST":
        status = 400
        if form.is_valid():
            try:
                with transaction.atomic():
                    _service().map_import(
                        actor=request.user,
                        batch_id=batch_id,
                        mapping=form.mapping(),
                        expected_revision=_revision(request),
                    )
            except (Forbidden, NotFound):
                raise Http404 from None
            except InvalidInput as error:
                patient_forms.apply_service_errors(form, error)
            except Conflict as error:
                form.add_error(None, conflict_text(error))
            else:
                messages.success(request, gettext("Mapeamento salvo. A validação das linhas está na fila."))
                return redirect("med_patients:import", organization_id, batch_id)
    return render(
        request,
        "med_patients/import.html",
        {
            "organization_id": organization_id,
            "batch": batch,
            "form": form,
            "mappable": batch.status in ("uploaded", "validated"),
        },
        status=status,
    )


@require_POST
@tenant_page()
def import_apply(request: HttpRequest, organization_id: UUID, batch_id: UUID) -> HttpResponse:
    try:
        with transaction.atomic():
            _service().apply_import(actor=request.user, batch_id=batch_id, expected_revision=_revision(request))
    except (Forbidden, NotFound):
        raise Http404 from None
    except Conflict as error:
        messages.error(request, conflict_text(error))
    else:
        messages.success(request, gettext("Importação iniciada. Acompanhe o andamento nesta página."))
    return redirect("med_patients:import", organization_id, batch_id)


@tenant_page()
def import_report(request: HttpRequest, organization_id: UUID, batch_id: UUID) -> HttpResponse:
    import csv

    from .importer import safe_cell

    try:
        batch = _service().import_status(actor=request.user, batch_id=batch_id)
    except (Forbidden, NotFound, InvalidInput):
        raise Http404 from None
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = 'attachment; filename="relatorio-importacao.csv"'
    writer = csv.writer(response)
    writer.writerow([gettext("linha"), gettext("código")])
    for row, code in batch.report:
        writer.writerow([row, safe_cell(code)])
    return response


# ----------------------------------------------------------------------------------- privacy


@tenant_page()
def patient_privacy(request: HttpRequest, organization_id: UUID, patient_id: UUID) -> HttpResponse:
    patient = _patient_or_404(request, patient_id)
    try:
        report = _service().data_report(actor=request.user, patient_id=patient_id)
    except (Forbidden, NotFound):
        raise Http404 from None
    context = patient_context(request, organization_id, patient, "privacy")
    context.update({"report": report})
    return render(request, "med_patients/privacy.html", context)


@require_POST
@tenant_page()
def patient_restrict(request: HttpRequest, organization_id: UUID, patient_id: UUID) -> HttpResponse:
    try:
        with transaction.atomic():
            _service().restrict_processing(
                actor=request.user,
                patient_id=patient_id,
                restricted=request.POST.get("restricted") == "1",
                expected_revision=_revision(request),
            )
    except (Forbidden, NotFound):
        raise Http404 from None
    except Conflict as error:
        messages.error(request, conflict_text(error))
    else:
        messages.success(request, gettext("Restrição de tratamento atualizada."))
    return redirect("med_patients:privacy", organization_id, patient_id)


@require_POST
@tenant_page()
def patient_anonymize(request: HttpRequest, organization_id: UUID, patient_id: UUID) -> HttpResponse:
    patient = _patient_or_404(request, patient_id)
    if request.POST.get("confirm_code", "").strip().upper() != patient.code:
        messages.error(request, gettext("Digite o código do paciente para confirmar a anonimização."))
        return redirect("med_patients:privacy", organization_id, patient_id)
    try:
        with transaction.atomic():
            _service().anonymize(actor=request.user, patient_id=patient_id, expected_revision=_revision(request))
    except (Forbidden, NotFound):
        raise Http404 from None
    except Conflict as error:
        detail = str(error.detail) if error.code == "retention" else conflict_text(error)
        messages.error(request, detail)
    else:
        messages.success(request, gettext("Paciente anonimizado."))
    return redirect("med_patients:privacy", organization_id, patient_id)
