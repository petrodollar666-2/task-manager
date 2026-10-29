"""Tính trạng thái "ai đang làm gì" từ lịch dạy và lịch vắng mặt.

Các hàm ở đây thuần logic (chỉ đọc DB), dễ kiểm thử, dùng chung cho
trang Tổng quan và trang Lịch dạy.
"""
from dataclasses import dataclass, field
from datetime import date

from django.utils import timezone

from .models import Absence, TeachingSlot

TEACHING = "teaching"
ABSENT = "absent"
FREE = "free"

ABSENCE_LABELS = {
    Absence.Kind.BUSINESS_TRIP: "Đi công tác",
    Absence.Kind.LEAVE: "Nghỉ phép",
    Absence.Kind.MEETING: "Họp",
    Absence.Kind.OTHER: "Vắng mặt",
}

BADGE_CLASSES = {
    TEACHING: "bg-amber-100 text-amber-800 ring-amber-200",
    FREE: "bg-green-100 text-green-800 ring-green-200",
    Absence.Kind.BUSINESS_TRIP: "bg-purple-100 text-purple-800 ring-purple-200",
    Absence.Kind.MEETING: "bg-purple-100 text-purple-800 ring-purple-200",
    Absence.Kind.LEAVE: "bg-slate-200 text-slate-700 ring-slate-300",
    Absence.Kind.OTHER: "bg-slate-200 text-slate-700 ring-slate-300",
}


@dataclass
class Status:
    code: str  # "teaching" | "absent" | "free"
    label: str
    detail: str = ""
    until: object = None  # time (hết tiết) hoặc datetime (hết vắng mặt) hoặc None
    until_text: str = ""  # đã định dạng sẵn cho template
    kind: str = ""  # loại vắng mặt (nếu code == "absent")
    source: object = field(default=None, repr=False)  # TeachingSlot / Absence gốc

    @property
    def is_teaching(self):
        return self.code == TEACHING

    @property
    def is_absent(self):
        return self.code == ABSENT

    @property
    def is_free(self):
        return self.code == FREE

    @property
    def badge_class(self):
        key = self.kind if self.code == ABSENT else self.code
        return BADGE_CLASSES.get(key, BADGE_CLASSES[FREE])


def _local(now=None):
    return timezone.localtime(now or timezone.now())


def _pk(obj):
    return getattr(obj, "pk", obj)


def slot_detail(slot):
    parts = [slot.course]
    if slot.room:
        parts.append(f"Phòng {slot.room}")
    return " · ".join(parts)


def _status_from_slot(slot):
    return Status(
        code=TEACHING,
        label="Đang lên lớp",
        detail=slot_detail(slot),
        until=slot.end_time,
        until_text=f"đến {slot.end_time:%H:%M}",
        source=slot,
    )


def _status_from_absence(absence, local_now):
    end = timezone.localtime(absence.end)
    if end.date() == local_now.date():
        until_text = f"đến {end:%H:%M}"
    else:
        until_text = f"đến {end:%H:%M} {end:%d/%m/%Y}"
    return Status(
        code=ABSENT,
        label=ABSENCE_LABELS.get(absence.kind, "Vắng mặt"),
        detail=absence.note or absence.get_kind_display(),
        until=end,
        until_text=until_text,
        kind=absence.kind,
        source=absence,
    )


def free_status():
    return Status(code=FREE, label="Rảnh")


def active_absences(now=None):
    """Queryset các lịch vắng mặt đang diễn ra tại thời điểm now."""
    now = now or timezone.now()
    return Absence.objects.filter(start__lte=now, end__gt=now)


def slots_on(day: date):
    """Queryset các buổi dạy diễn ra vào ngày `day` (đúng thứ, trong học kỳ)."""
    return TeachingSlot.objects.filter(
        weekday=day.weekday(), term_start__lte=day, term_end__gte=day
    )


def active_slots(now=None):
    """Queryset các buổi dạy đang diễn ra tại thời điểm now (giờ địa phương)."""
    local = _local(now)
    t = local.time().replace(tzinfo=None)
    return slots_on(local.date()).filter(start_time__lte=t, end_time__gt=t)


def statuses_for(users, now=None):
    """Trạng thái hiện tại cho nhiều người: dict user_id -> Status.

    Chỉ dùng 2 truy vấn (vắng mặt + lịch dạy), không phụ thuộc số người.
    Vắng mặt được ưu tiên hơn lịch dạy.
    """
    local = _local(now)
    ids = [_pk(u) for u in users]
    result = {uid: free_status() for uid in ids}
    if not ids:
        return result

    for slot in active_slots(local).filter(teacher_id__in=ids).order_by("start_time", "pk"):
        if result[slot.teacher_id].code == FREE:
            result[slot.teacher_id] = _status_from_slot(slot)

    for absence in active_absences(local).filter(user_id__in=ids).order_by("start", "pk"):
        if result[absence.user_id].code != ABSENT:
            result[absence.user_id] = _status_from_absence(absence, local)

    return result


def current_status(user, now=None):
    """Trạng thái hiện tại của một người (Status)."""
    return statuses_for([user], now)[_pk(user)]


def next_slot(user, now=None):
    """Buổi dạy kế tiếp trong hôm nay (chưa bắt đầu), hoặc None."""
    local = _local(now)
    t = local.time().replace(tzinfo=None)
    return (
        slots_on(local.date())
        .filter(teacher_id=_pk(user), start_time__gt=t)
        .order_by("start_time")
        .first()
    )


# ---------------------------------------------------------------------------
# Tóm tắt tiến độ từ dữ liệu đã prefetch (tránh N+1 khi hiển thị danh sách)
# ---------------------------------------------------------------------------

def summarize_project(project):
    """Gắn `pct` (tiến độ %) và `cur_step` (bước đang làm) vào project.

    Yêu cầu project.steps đã được prefetch; không phát sinh truy vấn mới.
    """
    from tasks.models import Step

    steps = sorted(project.steps.all(), key=lambda s: (s.order, s.pk))
    total = len(steps)
    done = sum(1 for s in steps if s.status == Step.Status.DONE)
    if total:
        project.pct = round(done * 100 / total)
    else:
        project.pct = 100 if project.status == project.Status.DONE else 0
    project.cur_step = next((s for s in steps if s.status != Step.Status.DONE), None)
    return project


def summarize_proposal(proposal):
    """Gắn `signed`, `total`, `cur_stage` vào tờ trình (stages đã prefetch)."""
    from approvals.models import ApprovalStage

    stages = sorted(proposal.stages.all(), key=lambda s: (s.order, s.pk))
    proposal.total = len(stages)
    proposal.signed = sum(1 for s in stages if s.status == ApprovalStage.Status.SIGNED)
    proposal.cur_stage = next(
        (s for s in stages if s.status != ApprovalStage.Status.SIGNED), None
    )
    return proposal

