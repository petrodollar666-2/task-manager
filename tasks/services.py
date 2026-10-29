from django.utils import timezone

from .models import Step, StepTemplate


def create_steps_from_templates(project):
    """Sinh các bước mặc định theo loại đầu việc. Trả về danh sách bước đã tạo."""
    templates = StepTemplate.objects.filter(kind=project.kind).order_by("order", "id")
    steps = [
        Step(project=project, order=i, name=t.name)
        for i, t in enumerate(templates, start=1)
    ]
    return Step.objects.bulk_create(steps)


def set_step_status(step, status):
    """Đổi trạng thái bước; đặt/xoá completed_at tương ứng."""
    step.status = status
    if status == Step.Status.DONE:
        if not step.completed_at:
            step.completed_at = timezone.now()
    else:
        step.completed_at = None
    step.save(update_fields=["status", "completed_at"])
    return step


NEXT_STATUS = {
    Step.Status.TODO: Step.Status.DOING,
    Step.Status.DOING: Step.Status.DONE,
    Step.Status.DONE: Step.Status.TODO,
}
