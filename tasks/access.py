"""Quy tắc phân quyền cho đầu việc (Project) và bước (Step)."""

from django.db.models import Q

from .models import Project, Step


def projects_visible_to(user, queryset=None):
    """Sếp thấy tất cả; giảng viên thấy đầu việc mình phụ trách
    hoặc có bước được giao cho mình."""
    qs = Project.objects.all() if queryset is None else queryset
    if user.is_boss:
        return qs
    assigned = Step.objects.filter(assignee=user).values("project_id")
    return qs.filter(Q(owner=user) | Q(pk__in=assigned))


def can_edit_project(user, project):
    return user.is_boss or project.owner_id == user.id


def can_view_project(user, project):
    return can_edit_project(user, project) or project.steps.filter(assignee=user).exists()


def can_change_step(user, step):
    return step.assignee_id == user.id or can_edit_project(user, step.project)
