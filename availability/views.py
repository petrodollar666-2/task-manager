from datetime import timedelta

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db.models import F, Prefetch, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone

from approvals.models import ApprovalStage, Proposal
from tasks.models import Project, ProjectKind, Step

from . import services
from .forms import AbsenceForm, TeachingSlotForm
from .models import Absence, TeachingSlot

User = get_user_model()

WEEKDAYS = TeachingSlot.Weekday.choices  # [(0, "Thứ 2"), ..., (6, "Chủ nhật")]


# ---------------------------------------------------------------------------
# Tổng quan
# ---------------------------------------------------------------------------

def _members():
    return (User.objects.filter(role=User.Role.MEMBER, is_active=True, is_superuser=False)
            .order_by("full_name", "username"))


def _overdue_steps():
    today = timezone.localdate()
    return (Step.objects.filter(deadline__lt=today)
            .exclude(status=Step.Status.DONE)
            .exclude(project__status=Project.Status.DONE)
            .select_related("project", "assignee")
            .order_by("deadline", "project__title"))


def _steps_prefetch():
    return Prefetch("steps", queryset=Step.objects.select_related("assignee").order_by("order", "id"))


def _stages_prefetch():
    return Prefetch("stages", queryset=ApprovalStage.objects.order_by("order", "id"))


def _member_rows(now=None, overdue_steps=None):
    """Dữ liệu bảng "Ai đang làm gì": mỗi giảng viên kèm trạng thái, đầu việc, số việc trễ.

    Số truy vấn cố định (không phụ thuộc số giảng viên / đầu việc).
    """
    members = list(_members())
    statuses = services.statuses_for(members, now)

    projects = [services.summarize_project(p) for p in
                Project.objects.filter(status=Project.Status.ACTIVE)
                .select_related("owner").prefetch_related(_steps_prefetch())
                .order_by("deadline", "title")]
    by_user = {m.pk: [] for m in members}
    for p in projects:
        involved = {p.owner_id}
        involved.update(s.assignee_id for s in p.steps.all()
                        if s.assignee_id and s.status != Step.Status.DONE)
        for uid in involved:
            if uid in by_user:
                by_user[uid].append(p)

    if overdue_steps is None:
        overdue_steps = list(_overdue_steps())
    overdue_count = {}
    for s in overdue_steps:
        if s.assignee_id:
            overdue_count[s.assignee_id] = overdue_count.get(s.assignee_id, 0) + 1

    return [
        {
            "user": m,
            "status": statuses[m.pk],
            "projects": by_user[m.pk],
            "overdue": overdue_count.get(m.pk, 0),
        }
        for m in members
    ]


@login_required
def dashboard(request):
    if request.user.is_boss:
        return _boss_dashboard(request)
    return _member_dashboard(request)


def _boss_dashboard(request):
    now = timezone.now()
    today = timezone.localdate()
    overdue_steps = list(_overdue_steps())
    rows = _member_rows(now, overdue_steps)

    proposals = [services.summarize_proposal(p) for p in
                 Proposal.objects.filter(status=Proposal.Status.IN_PROGRESS)
                 .select_related("owner").prefetch_related(_stages_prefetch())
                 .order_by("submitted_at", "created_at")]

    workshops = [services.summarize_project(p) for p in
                 Project.objects.filter(kind=ProjectKind.WORKSHOP,
                                        event_date__gte=today,
                                        event_date__lte=today + timedelta(days=30))
                 .select_related("owner").prefetch_related(_steps_prefetch())
                 .order_by("event_date")]

    active_projects = Project.objects.filter(status=Project.Status.ACTIVE)
    stats = {
        "active_projects": active_projects.count(),
        "overdue_projects": active_projects.filter(deadline__lt=today).count(),
        "proposals_in_progress": len(proposals),
        "teaching_now": sum(1 for r in rows if r["status"].is_teaching),
        "absent_now": sum(1 for r in rows if r["status"].is_absent),
        "members": len(rows),
    }
    return render(request, "availability/dashboard_boss.html", {
        "now": now,
        "stats": stats,
        "rows": rows,
        "proposals": proposals,
        "workshops": workshops,
        "overdue_steps": overdue_steps,
    })


@login_required
def status_table(request):
    """Phần bảng "Ai đang làm gì" để HTMX tự làm mới mỗi 60 giây."""
    if not request.user.is_boss:
        raise PermissionDenied
    return render(request, "availability/_member_table.html", {
        "rows": _member_rows(),
        "now": timezone.now(),
    })


def _member_dashboard(request):
    user = request.user
    now = timezone.now()
    status = services.current_status(user, now)
    nxt = services.next_slot(user, now)

    my_steps = list(Step.objects.filter(assignee=user)
                    .exclude(status=Step.Status.DONE)
                    .exclude(project__status=Project.Status.DONE)
                    .select_related("project")
                    .order_by(F("deadline").asc(nulls_last=True), "project__title", "order"))

    my_projects = [services.summarize_project(p) for p in
                   Project.objects.filter(owner=user)
                   .exclude(status=Project.Status.DONE)
                   .prefetch_related(_steps_prefetch())
                   .order_by(F("deadline").asc(nulls_last=True), "title")]

    my_proposals = [services.summarize_proposal(p) for p in
                    Proposal.objects.filter(owner=user)
                    .exclude(status=Proposal.Status.APPROVED)
                    .prefetch_related(_stages_prefetch())
                    .order_by("-created_at")]

    upcoming_absences = (Absence.objects.filter(user=user, end__gt=now)
                         .order_by("start")[:5])

    return render(request, "availability/dashboard_member.html", {
        "now": now,
        "status": status,
        "next_slot": nxt,
        "my_steps": my_steps,
        "my_projects": my_projects,
        "my_proposals": my_proposals,
        "upcoming_absences": upcoming_absences,
    })


# ---------------------------------------------------------------------------
# Lịch dạy & vắng mặt
# ---------------------------------------------------------------------------

def _int_or_none(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


@login_required
def schedule(request):
    user = request.user
    now = timezone.now()
    today = timezone.localdate()

    teacher_id = None
    teachers = None
    if user.is_boss:
        teacher_id = _int_or_none(request.GET.get("teacher"))
        teachers = User.objects.filter(
            Q(role=User.Role.MEMBER, is_active=True) | Q(teaching_slots__isnull=False)
        ).distinct().order_by("full_name", "username")
    else:
        teacher_id = user.pk

    slots = TeachingSlot.objects.select_related("teacher")
    absences = Absence.objects.select_related("user").filter(end__gt=now)
    if teacher_id:
        slots = slots.filter(teacher_id=teacher_id)
        absences = absences.filter(user_id=teacher_id)

    current = list(slots.filter(term_start__lte=today, term_end__gte=today)
                   .order_by("start_time", "teacher__full_name"))
    now_t = timezone.localtime(now).time().replace(tzinfo=None)
    for s in current:
        s.is_now = s.weekday == today.weekday() and s.start_time <= now_t < s.end_time
    columns = [
        {"weekday": wd, "label": label, "is_today": wd == today.weekday(),
         "slots": [s for s in current if s.weekday == wd]}
        for wd, label in WEEKDAYS
    ]
    other_slots = list(slots.exclude(term_start__lte=today, term_end__gte=today)
                       .filter(term_end__gte=today)
                       .order_by("term_start", "weekday", "start_time"))

    return render(request, "availability/schedule.html", {
        "columns": columns,
        "has_current": bool(current),
        "other_slots": other_slots,
        "absences": absences.order_by("start"),
        "teachers": teachers,
        "teacher_id": teacher_id,
        "today": today,
        "now": now,
    })


def _schedule_url(request):
    url = reverse("availability:schedule")
    teacher = _int_or_none(request.GET.get("teacher"))
    if teacher and request.user.is_boss:
        url += f"?teacher={teacher}"
    return url


def _check_owner(request, owner_id):
    if not request.user.is_boss and owner_id != request.user.pk:
        raise PermissionDenied("Bạn chỉ được sửa lịch của chính mình.")


def _edit(request, form_class, instance, title, success_msg, initial=None):
    if request.method == "POST":
        form = form_class(request.POST, instance=instance, user=request.user)
        if form.is_valid():
            form.save()
            messages.success(request, success_msg)
            return redirect(_schedule_url(request))
    else:
        form = form_class(instance=instance, user=request.user, initial=initial)
    return render(request, "availability/form.html", {
        "form": form,
        "title": title,
        "cancel_url": _schedule_url(request),
    })


def _delete(request, obj, title, description, success_msg):
    if request.method == "POST":
        obj.delete()
        messages.success(request, success_msg)
        return redirect(_schedule_url(request))
    return render(request, "availability/confirm_delete.html", {
        "title": title,
        "description": description,
        "cancel_url": _schedule_url(request),
    })


def _initial_owner(request):
    """Sếp mở form từ trang đã lọc theo giảng viên thì chọn sẵn giảng viên đó."""
    if request.user.is_boss:
        return _int_or_none(request.GET.get("teacher"))
    return request.user.pk


@login_required
def slot_create(request):
    initial = {}
    owner = _initial_owner(request)
    if owner:
        initial["teacher"] = owner
        # Gợi ý học kỳ theo buổi dạy gần nhất của giảng viên.
        last = TeachingSlot.objects.filter(teacher_id=owner).order_by("-term_end").first()
        if last:
            initial.update(term_start=last.term_start, term_end=last.term_end)
    return _edit(request, TeachingSlotForm, None, "Thêm buổi dạy",
                 "Đã thêm buổi dạy.", initial)


@login_required
def slot_edit(request, pk):
    slot = get_object_or_404(TeachingSlot, pk=pk)
    _check_owner(request, slot.teacher_id)
    return _edit(request, TeachingSlotForm, slot, "Sửa buổi dạy", "Đã cập nhật buổi dạy.")


@login_required
def slot_delete(request, pk):
    slot = get_object_or_404(TeachingSlot, pk=pk)
    _check_owner(request, slot.teacher_id)
    desc = (f"{slot.get_weekday_display()} {slot.start_time:%H:%M}–{slot.end_time:%H:%M} · "
            f"{services.slot_detail(slot)} ({slot.teacher})")
    return _delete(request, slot, "Xoá buổi dạy", desc, "Đã xoá buổi dạy.")


@login_required
def absence_create(request):
    initial = {}
    owner = _initial_owner(request)
    if owner:
        initial["user"] = owner
    return _edit(request, AbsenceForm, None, "Thêm lịch vắng mặt",
                 "Đã thêm lịch vắng mặt.", initial)


@login_required
def absence_edit(request, pk):
    absence = get_object_or_404(Absence, pk=pk)
    _check_owner(request, absence.user_id)
    return _edit(request, AbsenceForm, absence, "Sửa lịch vắng mặt",
                 "Đã cập nhật lịch vắng mặt.")


@login_required
def absence_delete(request, pk):
    absence = get_object_or_404(Absence, pk=pk)
    _check_owner(request, absence.user_id)
    start = timezone.localtime(absence.start)
    end = timezone.localtime(absence.end)
    desc = (f"{absence.get_kind_display()} của {absence.user}: "
            f"{start:%H:%M %d/%m/%Y} – {end:%H:%M %d/%m/%Y}"
            + (f" · {absence.note}" if absence.note else ""))
    return _delete(request, absence, "Xoá lịch vắng mặt", desc, "Đã xoá lịch vắng mặt.")
