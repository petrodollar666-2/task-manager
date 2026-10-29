import os

from django.conf import settings
from django.contrib.postgres.indexes import GinIndex
from django.contrib.postgres.search import SearchVector, SearchVectorField
from django.db import DatabaseError, models, transaction
from django.db.models import F, Func, Q
from django.db.models.functions import Left

# Giới hạn độ dài văn bản đưa vào tsvector (tsvector tối đa ~1MB).
VECTOR_TEXT_LIMITS = (None, 300_000, 50_000)


def unaccent(expression):
    """unaccent(expr) – bỏ dấu tiếng Việt (đ → d) ở phía Postgres."""
    if isinstance(expression, str):
        expression = F(expression)
    return Func(expression, function="unaccent", output_field=models.TextField())


def build_search_vector(text_limit=None):
    content = F("extracted_text") if text_limit is None else Left("extracted_text", text_limit)
    return (
        SearchVector(unaccent("name"), config="simple", weight="A")
        + SearchVector(unaccent("description"), config="simple", weight="B")
        + SearchVector(unaccent(content), config="simple", weight="C")
    )


class DocumentQuerySet(models.QuerySet):
    def visible_to(self, user):
        """Sếp thấy tất cả; giảng viên thấy tài liệu của mình hoặc gắn với
        đầu việc / tờ trình mình phụ trách."""
        if not user.is_authenticated:
            return self.none()
        if user.is_boss:
            return self
        return self.filter(Q(owner=user) | Q(project__owner=user) | Q(proposal__owner=user))

    def update_search_vectors(self):
        """Tính lại search_vector cho các tài liệu trong queryset."""
        for limit in VECTOR_TEXT_LIMITS:
            try:
                with transaction.atomic():
                    return self.update(search_vector=build_search_vector(limit))
            except DatabaseError:
                # Văn bản quá dài cho tsvector → thử lại với nội dung ngắn hơn.
                if len(self) > 1:
                    return sum(self.filter(pk=d.pk).update_search_vectors() for d in self)
                continue
        return self.update(search_vector=build_search_vector(0))


class Document(models.Model):
    class Source(models.TextChoices):
        UPLOAD = "upload", "Tải lên"
        DRIVE = "drive", "Google Drive"

    name = models.CharField("Tên file", max_length=255)
    description = models.TextField("Mô tả", blank=True)
    file = models.FileField("File", upload_to="documents/%Y/%m/", blank=True, max_length=255)
    original_filename = models.CharField("Tên file gốc", max_length=255, blank=True)
    source = models.CharField("Nguồn", max_length=10, choices=Source.choices, default=Source.UPLOAD)
    drive_file_id = models.CharField(max_length=128, blank=True, db_index=True)
    drive_url = models.URLField("Link Drive", blank=True, max_length=500)
    drive_modified_time = models.DateTimeField("Sửa đổi trên Drive", null=True, blank=True)
    mime_type = models.CharField(max_length=150, blank=True)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True,
                              blank=True, related_name="documents", verbose_name="Người tải lên")
    project = models.ForeignKey("tasks.Project", on_delete=models.SET_NULL, null=True, blank=True,
                                related_name="documents", verbose_name="Thuộc đầu việc")
    proposal = models.ForeignKey("approvals.Proposal", on_delete=models.SET_NULL, null=True,
                                 blank=True, related_name="documents", verbose_name="Thuộc tờ trình")
    extracted_text = models.TextField(blank=True)
    search_vector = SearchVectorField(null=True, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = DocumentQuerySet.as_manager()

    class Meta:
        verbose_name = "Tài liệu"
        verbose_name_plural = "Tài liệu"
        ordering = ["-created_at"]
        indexes = [GinIndex(fields=["search_vector"], name="files_doc_search_gin")]

    def __str__(self):
        return self.name

    SEARCH_FIELDS = {"name", "description", "extracted_text"}

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        update_fields = kwargs.get("update_fields")
        if update_fields is None or self.SEARCH_FIELDS & set(update_fields):
            self.update_search_vector()

    def update_search_vector(self):
        # unaccent() không IMMUTABLE nên không dùng generated column được;
        # tính lại bằng một câu UPDATE sau mỗi lần lưu.
        Document.objects.filter(pk=self.pk).update_search_vectors()

    # --- Tiện ích ---
    @property
    def download_filename(self):
        if self.original_filename:
            return self.original_filename
        return os.path.basename(self.file.name) if self.file else ""

    @property
    def extension(self):
        name = self.download_filename or self.name
        return os.path.splitext(name)[1].lower().lstrip(".")

    def can_view(self, user):
        return Document.objects.visible_to(user).filter(pk=self.pk).exists()

    def can_edit(self, user):
        return user.is_authenticated and (user.is_boss or self.owner_id == user.pk)

    def reextract(self, save=True):
        """Trích xuất lại nội dung từ file đã lưu. Trả về số ký tự."""
        from .extract import extract_text

        if not self.file:
            return len(self.extracted_text)
        try:
            with self.file.open("rb") as fh:
                text = extract_text(fh, self.download_filename or self.file.name, self.mime_type)
        except (OSError, ValueError):
            text = ""
        self.extracted_text = text
        if save:
            self.save(update_fields=["extracted_text", "updated_at"])
        return len(text)
