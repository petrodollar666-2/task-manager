from django.db import transaction
from django.utils import timezone

from .models import ApprovalRouteTemplate, ApprovalStage, Proposal


def create_stages_from_templates(proposal):
    """Sinh các chặng ký theo tuyến ký mẫu của loại tờ trình."""
    templates = ApprovalRouteTemplate.objects.filter(kind=proposal.kind).order_by("order", "id")
    stages = [
        ApprovalStage(proposal=proposal, order=i, department=t.department, signer_name=t.signer_name)
        for i, t in enumerate(templates, start=1)
    ]
    return ApprovalStage.objects.bulk_create(stages)


def normalize_stage_order(proposal):
    """Đánh lại thứ tự 1..n cho các chặng."""
    stages = list(proposal.stages.order_by("order", "id"))
    changed = []
    for i, stage in enumerate(stages, start=1):
        if stage.order != i:
            stage.order = i
            changed.append(stage)
    if changed:
        ApprovalStage.objects.bulk_update(changed, ["order"])
    return stages


@transaction.atomic
def move_stage(stage, direction):
    """Đổi chỗ chặng với chặng liền trước (up) hoặc liền sau (down)."""
    stages = normalize_stage_order(stage.proposal)
    idx = next(i for i, s in enumerate(stages) if s.pk == stage.pk)
    other_idx = idx - 1 if direction == "up" else idx + 1
    if other_idx < 0 or other_idx >= len(stages):
        return False
    a, b = stages[idx], stages[other_idx]
    a.order, b.order = b.order, a.order
    ApprovalStage.objects.bulk_update([a, b], ["order"])
    return True


def sign_stage(stage, note=""):
    stage.status = ApprovalStage.Status.SIGNED
    stage.signed_at = timezone.now()
    if note:
        stage.note = note
    stage.save(update_fields=["status", "signed_at", "note"])
    proposal = stage.proposal
    if not proposal.submitted_at:
        proposal.submitted_at = timezone.localdate()
        proposal.save(update_fields=["submitted_at", "updated_at"])
    proposal.refresh_status()
    return stage


def reject_stage(stage, note=""):
    stage.status = ApprovalStage.Status.REJECTED
    stage.signed_at = None
    stage.note = note
    stage.save(update_fields=["status", "signed_at", "note"])
    stage.proposal.refresh_status()
    return stage


def reset_stage(stage):
    """Hoàn tác chặng về trạng thái chờ ký."""
    stage.status = ApprovalStage.Status.PENDING
    stage.signed_at = None
    stage.save(update_fields=["status", "signed_at"])
    recompute_status(stage.proposal)
    return stage


def recompute_status(proposal):
    """Tính lại trạng thái từ đầu (cho phép thoát khỏi 'Bị trả lại' khi không còn chặng bị trả)."""
    proposal.status = Proposal.Status.DRAFT
    return proposal.refresh_status()


def submit_proposal(proposal):
    """Nộp trình ký (hoặc nộp lại sau khi bị trả lại)."""
    if proposal.status == Proposal.Status.REJECTED:
        proposal.stages.filter(status=ApprovalStage.Status.REJECTED).update(
            status=ApprovalStage.Status.PENDING
        )
    if proposal.status in (Proposal.Status.DRAFT, Proposal.Status.REJECTED) or not proposal.submitted_at:
        proposal.submitted_at = timezone.localdate()
        proposal.save(update_fields=["submitted_at", "updated_at"])
    return recompute_status(proposal)
