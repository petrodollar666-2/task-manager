from django.contrib import admin, messages

from .models import Document


@admin.register(Document)
class DocumentAdmin(admin.ModelAdmin):
    list_display = ("name", "source", "owner", "project", "proposal", "created_at")
    list_filter = ("source", "created_at")
    search_fields = ("name", "description", "original_filename")
    raw_id_fields = ("owner", "project", "proposal")
    readonly_fields = ("drive_file_id", "drive_url", "drive_modified_time", "mime_type",
                       "original_filename", "created_at", "updated_at")
    date_hierarchy = "created_at"
    actions = ["reextract_content"]

    @admin.action(description="Trích xuất lại nội dung")
    def reextract_content(self, request, queryset):
        count = chars = 0
        for doc in queryset:
            if doc.file:
                chars += doc.reextract()
                count += 1
        queryset.update_search_vectors()
        self.message_user(
            request,
            f"Đã trích xuất lại {count} tài liệu ({chars:,} ký tự) và cập nhật chỉ mục tìm kiếm.",
            messages.SUCCESS,
        )
