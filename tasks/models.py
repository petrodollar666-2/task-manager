from django.conf import settings
from django.db import models
from django.utils import timezone


class ProjectKind(models.TextChoices):
    WORKSHOP = "workshop", "Workshop"
    WORKING_PAPER = "working_paper", "Working paper"
    OTHER = "other", "Khác"


class Project(models.Model):
    """Một đầu việc: một workshop, một bài working paper, ..."""

    class Status(models.TextChoices):
        ACTIVE = "active", "Đang thực hiện"
        DONE = "done", "Hoàn thành"
        PAUSED = "paused", "Tạm dừng"

    title = models.CharField("Tên đầu việc", max_length=255)
    kind = models.CharField("Loại", max_length=20, choices=ProjectKind.choices, default=ProjectKind.OTHER)
    series = models.CharField("Chuỗi / series", max_length=255, blank=True,
                              help_text="Ví dụ: FTU Working Paper Series 2026")
    description = models.TextField("Mô tả", blank=True)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
                              related_name="projects", verbose_name="Người phụ trách")
    event_date = models.DateField("Ngày diễn ra", null=True, blank=True)
    deadline = models.DateField("Hạn hoàn thành", null=True, blank=True)
    status = models.CharField("Trạng thái", max_length=10, choices=Status.choices, default=Status.ACTIVE)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Đầu việc"
        verbose_name_plural = "Đầu việc"
        ordering = ["deadline", "-created_at"]

    def __str__(self):
        return self.title

    @property
    def progress(self):
        """Phần trăm số bước đã xong (0-100)."""
        total = self.steps.count()
        if not total:
            return 100 if self.status == self.Status.DONE else 0
        done = self.steps.filter(status=Step.Status.DONE).count()
        return round(done * 100 / total)

    @property
    def current_step(self):
        return self.steps.exclude(status=Step.Status.DONE).order_by("order").first()

    @property
    def is_overdue(self):
        return bool(self.deadline and self.status != self.Status.DONE
                    and self.deadline < timezone.localdate())


class Step(models.Model):
    class Status(models.TextChoices):
        TODO = "todo", "Chưa làm"
        DOING = "doing", "Đang làm"
        DONE = "done", "Đã xong"

    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="steps")
    order = models.PositiveIntegerField("Thứ tự", default=0)
    name = models.CharField("Tên bước", max_length=255)
    assignee = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True,
                                 blank=True, related_name="steps", verbose_name="Người làm")
    status = models.CharField("Trạng thái", max_length=10, choices=Status.choices, default=Status.TODO)
    deadline = models.DateField("Hạn", null=True, blank=True)
    note = models.TextField("Ghi chú", blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "Bước"
        verbose_name_plural = "Bước"
        ordering = ["project", "order", "id"]

    def __str__(self):
        return f"{self.order}. {self.name}"

    @property
    def is_overdue(self):
        return bool(self.deadline and self.status != self.Status.DONE
                    and self.deadline < timezone.localdate())


class StepTemplate(models.Model):
    """Bộ bước mẫu tự sinh khi tạo đầu việc theo loại."""

    kind = models.CharField("Loại đầu việc", max_length=20, choices=ProjectKind.choices)
    order = models.PositiveIntegerField("Thứ tự", default=0)
    name = models.CharField("Tên bước", max_length=255)

    class Meta:
        verbose_name = "Bước mẫu"
        verbose_name_plural = "Bước mẫu"
        ordering = ["kind", "order"]

    def __str__(self):
        return f"[{self.get_kind_display()}] {self.order}. {self.name}"
