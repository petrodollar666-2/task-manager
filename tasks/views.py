from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db.models import Case, F, IntegerField, Max, Prefetch, Value, When
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from accounts.permissions import visible_to

from .access import can_change_step, can_edit_project, can_view_project, projects_visible_to
from .forms import ProjectForm, StepForm, StepQuickAddForm
from .models import Project, ProjectKind, Step
from .services import NEXT_STATUS, create_steps_from_templates, set_step_status


def _is_htmx(request):
    return request.headers.get("HX-Request") == "true"


def _get_project(request, pk, edit=False):
    project = get_object_or_404(Project.objects.select_related("owner"), pk=pk)
    if not can_view_project(request.user, project):
        raise Http404("Không tìm thấy đầu việc")
    if edit and not can_edit_project(request.user, project):
        raise PermissionDenied("Bạn không có quyền sửa đầu việc này")
    return project


def _steps_context(request, project, add_form=None):
    steps = list(project.steps.select_related("assignee").order_by("order", "id"))
    total = len(steps)
    done = sum(1 for s in steps if s.status == Step.Status.DONE)
    if total:
        progress = round(done * 100 / total)
    else:
        progress = 100 if project.status == Project.Status.DONE else 0
    current = next((s for s in steps if s.status != Step.Status.DONE), None)
    can_edit = can_edit_project(request.user, project)
    for s in steps:
        s.can_change = can_edit or s.assignee_id == request.user.id
        s.is_current = current is not None and s.pk == current.pk
    return {
        "project": project,
        "steps": steps,
        "done_count": done,
        "total_count": total,
        "progress": progress,
        "current_step": current,
        "can_edit": can_edit,
        "add_form": add_form if add_form is not None else (StepQuickAddForm() if can_edit else None),
        "step_statuses": Step.Status.choices,
    }


def _steps_response(request, project, add_form=None):
    if _is_htmx(request):
        return render(request, "tasks/_steps.html", _steps_context(request, project, add_form))
    return redirect("tasks:detail", pk=project.pk)


# ---------------------------------------------------------------- Đầu việc

@login_required
def project_list(request):
    user = request.user
    qs = projects_visible_to(user).select_related("owner")

    q = request.GET.get("q", "").strip()
    kind = request.GET.get("kind", "")
    status = request.GET.get("status", "")
    owner = request.GET.get("owner", "")
    if q:
        qs = qs.filter(title__icontains=q)
    if kind in ProjectKind.values:
        qs = qs.filter(kind=kind)
    if status in Project.Status.values:
        qs = qs.filter(status=status)
    if user.is_boss and owner.isdigit():
        qs = qs.filter(owner_id=int(owner))

    kind_rank = Case(
        *[When(kind=k, then=Value(i)) for i, k in enumerate(ProjectKind.values)],
        default=Value(99),
        output_field=IntegerField(),
    )
    qs = (
        qs.annotate(kind_rank=kind_rank)
        .order_by("kind_rank", F("deadline").asc(nulls_last=True), "-created_at")
        .prefetch_related(
            Prefetch("steps", queryset=Step.objects.order_by("order", "id"), to_attr="ordered_steps")
        )
    )
    projects = list(qs)
    for p in projects:
        total = len(p.ordered_steps)
        done = sum(1 for s in p.ordered_steps if s.status == Step.Status.DONE)
        p.pct = round(done * 100 / total) if total else (100 if p.status == Project.Status.DONE else 0)
        p.cur = next((s for s in p.ordered_steps if s.status != Step.Status.DONE), None)
        p.done_count, p.total_count = done, total
        p.is_mine = p.owner_id == user.id

    context = {
        "projects": projects,
        "kinds": ProjectKind.choices,
        "statuses": Project.Status.choices,
        "owners": get_user_model().objects.filter(is_active=True) if user.is_boss else None,
        "f": {"q": q, "kind": kind, "status": status, "owner": owner},
        "has_filter": bool(q or kind or status or owner),
    }
    return render(request, "tasks/project_list.html", context)


@login_required
def project_detail(request, pk):
    project = _get_project(request, pk)
    context = _steps_context(request, project)
    context["proposals"] = visible_to(request.user, project.proposals.all()).prefetch_related("stages")
    context["documents"] = project.documents.all()
    return render(request, "tasks/project_detail.html", context)


@login_required
def project_create(request):
    form = ProjectForm(request.POST or None, user=request.user)
    if request.method == "POST" and form.is_valid():
        project = form.save(commit=False)
        if not request.user.is_boss:
            project.owner = request.user
        project.save()
        steps = create_steps_from_templates(project)
        msg = f"Đã tạo đầu việc “{project.title}”"
        if steps:
            msg += f" với {len(steps)} bước mặc định"
        messages.success(request, msg + ".")
        return redirect("tasks:detail", pk=project.pk)
    return render(request, "tasks/project_form.html", {"form": form, "project": None})


@login_required
def project_edit(request, pk):
    project = _get_project(request, pk, edit=True)
    form = ProjectForm(request.POST or None, instance=project, user=request.user)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Đã lưu thay đổi.")
        return redirect("tasks:detail", pk=project.pk)
    return render(request, "tasks/project_form.html", {"form": form, "project": project})


@login_required
@require_POST
def project_delete(request, pk):
    project = _get_project(request, pk, edit=True)
    title = project.title
    project.delete()
    messages.success(request, f"Đã xoá đầu việc “{title}”.")
    return redirect("tasks:list")


# ---------------------------------------------------------------- Bước

@login_required
@require_POST
def step_add(request, pk):
    project = _get_project(request, pk, edit=True)
    form = StepQuickAddForm(request.POST)
    if form.is_valid():
        step = form.save(commit=False)
        step.project = project
        step.order = (project.steps.aggregate(m=Max("order"))["m"] or 0) + 1
        step.save()
        return _steps_response(request, project)
    if not _is_htmx(request):
        messages.error(request, "Không thêm được bước: vui lòng nhập tên bước.")
    return _steps_response(request, project, add_form=form)


@login_required
@require_POST
def step_status(request, pk):
    step = get_object_or_404(Step.objects.select_related("project"), pk=pk)
    if not can_view_project(request.user, step.project):
        raise Http404("Không tìm thấy bước")
    if not can_change_step(request.user, step):
        raise PermissionDenied("Bạn chỉ được đổi trạng thái bước được giao cho mình")
    new_status = request.POST.get("status")
    if new_status not in Step.Status.values:
        new_status = NEXT_STATUS[step.status]
    set_step_status(step, new_status)
    return _steps_response(request, step.project)


@login_required
def step_edit(request, pk):
    step = get_object_or_404(Step.objects.select_related("project"), pk=pk)
    project = _get_project(request, step.project_id, edit=True)
    old_status = step.status
    form = StepForm(request.POST or None, instance=step)
    if request.method == "POST" and form.is_valid():
        step = form.save(commit=False)
        step.save()
        if step.status != old_status:
            set_step_status(step, step.status)
        messages.success(request, "Đã lưu bước.")
        return redirect("tasks:detail", pk=project.pk)
    return render(request, "tasks/step_form.html", {"form": form, "step": step, "project": project})


@login_required
@require_POST
def step_delete(request, pk):
    step = get_object_or_404(Step.objects.select_related("project"), pk=pk)
    project = _get_project(request, step.project_id, edit=True)
    step.delete()
    return _steps_response(request, project)
