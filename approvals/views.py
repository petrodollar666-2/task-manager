import os

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db.models import Max, Prefetch
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from accounts.permissions import visible_to

from .forms import AttachmentForm, ProposalForm, StageEditForm, StageForm
from .models import ApprovalStage, Proposal
from .services import (
    create_stages_from_templates,
    move_stage,
    recompute_status,
    reject_stage,
    reset_stage,
    sign_stage,
    submit_proposal,
)


def _is_htmx(request):
    return request.headers.get("HX-Request") == "true"


def _proposals_for(user):
    return visible_to(user, Proposal.objects.select_related("owner", "project"))


def _get_proposal(request, pk):
    """Sếp hoặc người trình mới được xem/thao tác; người khác nhận 404."""
    return get_object_or_404(_proposals_for(request.user), pk=pk)


def _get_stage(request, pk):
    stage = get_object_or_404(ApprovalStage.objects.select_related("proposal"), pk=pk)
    stage.proposal = _get_proposal(request, stage.proposal_id)
    return stage


def _ensure_editable(proposal):
    if proposal.status == Proposal.Status.APPROVED:
        raise PermissionDenied("Tờ trình đã ký đủ, không thể sửa tuyến ký")


def _panel_context(request, proposal, stage_form=None):
    stages = list(proposal.stages.order_by("order", "id"))
    signed = sum(1 for s in stages if s.status == ApprovalStage.Status.SIGNED)
    current = next((s for s in stages if s.status != ApprovalStage.Status.SIGNED), None)
    return {
        "proposal": proposal,
        "stages": stages,
        "signed": signed,
        "total": len(stages),
        "current_stage": current,
        "missing": [s for s in stages if s.status != ApprovalStage.Status.SIGNED],
        "editable": proposal.status != Proposal.Status.APPROVED,
        "stage_form": stage_form or StageForm(),
    }


def _panel_response(request, proposal, stage_form=None):
    if _is_htmx(request):
        proposal.refresh_from_db()
        return render(request, "approvals/_panel.html", _panel_context(request, proposal, stage_form))
    return redirect("approvals:detail", pk=proposal.pk)


# ---------------------------------------------------------------- Tờ trình

@login_required
def proposal_list(request):
    qs = _proposals_for(request.user).prefetch_related(
        Prefetch("stages", queryset=ApprovalStage.objects.order_by("order", "id"), to_attr="stage_list")
    )
    status = request.GET.get("status", "")
    kind = request.GET.get("kind", "")
    if status in Proposal.Status.values:
        qs = qs.filter(status=status)
    if kind in Proposal.Kind.values:
        qs = qs.filter(kind=kind)
    proposals = list(qs)
    for p in proposals:
        p.n_total = len(p.stage_list)
        p.n_signed = sum(1 for s in p.stage_list if s.status == ApprovalStage.Status.SIGNED)
        p.missing = [s for s in p.stage_list if s.status != ApprovalStage.Status.SIGNED]
        p.cur = p.missing[0] if p.missing else None
    return render(request, "approvals/proposal_list.html", {
        "proposals": proposals,
        "statuses": Proposal.Status.choices,
        "kinds": Proposal.Kind.choices,
        "f": {"status": status, "kind": kind},
        "has_filter": bool(status or kind),
    })


@login_required
def proposal_detail(request, pk):
    proposal = _get_proposal(request, pk)
    context = _panel_context(request, proposal)
    context["attachment_form"] = AttachmentForm()
    context["attachment_name"] = os.path.basename(proposal.attachment.name) if proposal.attachment else ""
    return render(request, "approvals/proposal_detail.html", context)


@login_required
def proposal_create(request):
    initial = {}
    if request.GET.get("project", "").isdigit():
        initial["project"] = int(request.GET["project"])
    form = ProposalForm(request.POST or None, request.FILES or None, user=request.user, initial=initial)
    if request.method == "POST" and form.is_valid():
        proposal = form.save(commit=False)
        proposal.owner = request.user
        proposal.save()
        stages = create_stages_from_templates(proposal)
        msg = f"Đã tạo tờ trình “{proposal.title}”"
        if stages:
            msg += f" với tuyến ký {len(stages)} chặng mặc định"
        messages.success(request, msg + ".")
        return redirect("approvals:detail", pk=proposal.pk)
    return render(request, "approvals/proposal_form.html", {"form": form, "proposal": None})


@login_required
def proposal_edit(request, pk):
    proposal = _get_proposal(request, pk)
    form = ProposalForm(request.POST or None, instance=proposal, user=request.user)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Đã lưu thay đổi.")
        return redirect("approvals:detail", pk=proposal.pk)
    return render(request, "approvals/proposal_form.html", {"form": form, "proposal": proposal})


@login_required
@require_POST
def proposal_delete(request, pk):
    proposal = _get_proposal(request, pk)
    title = proposal.title
    if proposal.attachment:
        proposal.attachment.delete(save=False)
    proposal.delete()
    messages.success(request, f"Đã xoá tờ trình “{title}”.")
    return redirect("approvals:list")


@login_required
@require_POST
def proposal_submit(request, pk):
    proposal = _get_proposal(request, pk)
    if proposal.status in (Proposal.Status.DRAFT, Proposal.Status.REJECTED):
        submit_proposal(proposal)
        if not _is_htmx(request):
            messages.success(request, "Đã nộp trình ký.")
    return _panel_response(request, proposal)


# ---------------------------------------------------------------- File đính kèm

@login_required
def attachment_download(request, pk):
    proposal = _get_proposal(request, pk)
    if not proposal.attachment:
        raise Http404("Tờ trình chưa có file đính kèm")
    try:
        fh = proposal.attachment.open("rb")
    except FileNotFoundError:
        raise Http404("Không tìm thấy file")
    return FileResponse(fh, as_attachment=True, filename=os.path.basename(proposal.attachment.name))


@login_required
@require_POST
def attachment_upload(request, pk):
    proposal = _get_proposal(request, pk)
    old_file = proposal.attachment.name if proposal.attachment else None
    form = AttachmentForm(request.POST, request.FILES, instance=proposal)
    if form.is_valid():
        form.save()
        if old_file and old_file != proposal.attachment.name:
            proposal.attachment.storage.delete(old_file)
        messages.success(request, "Đã cập nhật file đính kèm.")
    else:
        messages.error(request, "Vui lòng chọn file để tải lên.")
    return redirect("approvals:detail", pk=proposal.pk)


# ---------------------------------------------------------------- Chặng ký

@login_required
@require_POST
def stage_sign(request, pk):
    stage = _get_stage(request, pk)
    proposal = stage.proposal
    _ensure_editable(proposal)
    if proposal.current_stage != stage:
        raise PermissionDenied("Chỉ được ký chặng hiện tại")
    sign_stage(stage, note=request.POST.get("note", "").strip())
    return _panel_response(request, proposal)


@login_required
@require_POST
def stage_reject(request, pk):
    stage = _get_stage(request, pk)
    proposal = stage.proposal
    _ensure_editable(proposal)
    if proposal.current_stage != stage:
        raise PermissionDenied("Chỉ được trả lại ở chặng hiện tại")
    reject_stage(stage, note=request.POST.get("note", "").strip())
    return _panel_response(request, proposal)


@login_required
@require_POST
def stage_reset(request, pk):
    stage = _get_stage(request, pk)
    reset_stage(stage)
    return _panel_response(request, stage.proposal)


@login_required
@require_POST
def stage_add(request, pk):
    proposal = _get_proposal(request, pk)
    _ensure_editable(proposal)
    form = StageForm(request.POST)
    if form.is_valid():
        stage = form.save(commit=False)
        stage.proposal = proposal
        stage.order = (proposal.stages.aggregate(m=Max("order"))["m"] or 0) + 1
        stage.save()
        recompute_status(proposal)
        return _panel_response(request, proposal)
    if not _is_htmx(request):
        messages.error(request, "Vui lòng nhập tên phòng / đơn vị.")
    return _panel_response(request, proposal, stage_form=form)


@login_required
def stage_edit(request, pk):
    stage = _get_stage(request, pk)
    proposal = stage.proposal
    form = StageEditForm(request.POST or None, instance=stage)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Đã lưu chặng ký.")
        return redirect("approvals:detail", pk=proposal.pk)
    return render(request, "approvals/stage_form.html", {"form": form, "stage": stage, "proposal": proposal})


@login_required
@require_POST
def stage_delete(request, pk):
    stage = _get_stage(request, pk)
    proposal = stage.proposal
    _ensure_editable(proposal)
    stage.delete()
    recompute_status(proposal)
    return _panel_response(request, proposal)


@login_required
@require_POST
def stage_move(request, pk, direction):
    stage = _get_stage(request, pk)
    _ensure_editable(stage.proposal)
    if direction not in ("up", "down"):
        raise Http404
    move_stage(stage, direction)
    return _panel_response(request, stage.proposal)
