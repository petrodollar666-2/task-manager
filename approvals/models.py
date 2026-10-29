from django.conf import settings
from django.db import models


class Proposal(models.Model):
    """Tờ trình / kế hoạch tài chính cần đi xin chữ ký qua nhiều phòng."""

    class Kind(models.TextChoices):
        PROPOSAL = "proposal", "Tờ trình"
        FINANCE = "finance", "Kế hoạch tài chính"
        OTHER = "other", "Khác"

    class Status(models.TextChoices):
        DRAFT = "draft", "Đang soạn"
        IN_PROGRESS = "in_progress", "Đang trình ký"
        APPROVED = "approved", "Đã ký đủ"
        REJECTED = "rejected", "Bị trả lại"

    title = models.CharField("Tiêu đề", max_length=255)
    kind = models.CharField("Loại", max_length=20, choices=Kind.choices, default=Kind.PROPOSAL)
    project = models.ForeignKey("tasks.Project", on_delete=models.SET_NULL, null=True, blank=True,
                                related_name="proposals", verbose_name="Thuộc đầu việc")
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
                              related_name="proposals", verbose_name="Người trình")
    amount = models.DecimalField("Số tiền (VNĐ)", max_digits=15, decimal_places=0, null=True, blank=True)
    attachment = models.FileField("File đính kèm", upload_to="proposals/%Y/%m/", blank=True)
    status = models.CharField("Trạng thái", max_length=20, choices=Status.choices, default=Status.DRAFT)
    submitted_at = models.DateField("Ngày trình", null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Tờ trình"
        verbose_name_plural = "Tờ trình"
        ordering = ["-created_at"]

    def __str__(self):
        return self.title

    @property
    def signed_count(self):
        return self.stages.filter(status=ApprovalStage.Status.SIGNED).count()

    @property
    def total_count(self):
        return self.stages.count()

    @property
    def remaining_count(self):
        return self.total_count - self.signed_count

    @property
    def current_stage(self):
        """Chặng đầu tiên chưa ký: tờ trình đang nằm ở phòng này."""
        return self.stages.exclude(status=ApprovalStage.Status.SIGNED).order_by("order").first()

    @property
    def missing_signers(self):
        return list(self.stages.exclude(status=ApprovalStage.Status.SIGNED).order_by("order"))

    def refresh_status(self, save=True):
        """Tính lại trạng thái tổng từ các chặng ký."""
        stages = list(self.stages.all())
        if any(s.status == ApprovalStage.Status.REJECTED for s in stages):
            self.status = self.Status.REJECTED
        elif stages and all(s.status == ApprovalStage.Status.SIGNED for s in stages):
            self.status = self.Status.APPROVED
        elif any(s.status == ApprovalStage.Status.SIGNED for s in stages) or self.submitted_at:
            self.status = self.Status.IN_PROGRESS
        else:
            self.status = self.Status.DRAFT
        if save:
            self.save(update_fields=["status", "updated_at"])
        return self.status


class ApprovalStage(models.Model):
    """Một chữ ký cần có: ở phòng nào, ai ký."""

    class Status(models.TextChoices):
        PENDING = "pending", "Chờ ký"
        SIGNED = "signed", "Đã ký"
        REJECTED = "rejected", "Trả lại"

    proposal = models.ForeignKey(Proposal, on_delete=models.CASCADE, related_name="stages")
    order = models.PositiveIntegerField("Thứ tự", default=0)
    department = models.CharField("Phòng / đơn vị", max_length=150)
    signer_name = models.CharField("Người ký", max_length=150, blank=True,
                                   help_text="Ví dụ: Trưởng phòng Kế hoạch - Tài chính")
    status = models.CharField("Trạng thái", max_length=10, choices=Status.choices, default=Status.PENDING)
    signed_at = models.DateTimeField("Thời điểm ký", null=True, blank=True)
    note = models.TextField("Ghi chú", blank=True)

    class Meta:
        verbose_name = "Chặng ký"
        verbose_name_plural = "Chặng ký"
        ordering = ["proposal", "order", "id"]

    def __str__(self):
        return f"{self.order}. {self.department} - {self.signer_name}"


class ApprovalRouteTemplate(models.Model):
    """Mẫu tuyến ký mặc định (sửa được trong trang quản trị)."""

    kind = models.CharField("Loại tờ trình", max_length=20, choices=Proposal.Kind.choices)
    order = models.PositiveIntegerField("Thứ tự", default=0)
    department = models.CharField("Phòng / đơn vị", max_length=150)
    signer_name = models.CharField("Người ký", max_length=150, blank=True)

    class Meta:
        verbose_name = "Tuyến ký mẫu"
        verbose_name_plural = "Tuyến ký mẫu"
        ordering = ["kind", "order"]

    def __str__(self):
        return f"[{self.get_kind_display()}] {self.order}. {self.department}"
