from django.contrib import admin

from .models import Project, Step, StepTemplate


class StepInline(admin.TabularInline):
    model = Step
    extra = 0
    fields = ["order", "name", "assignee", "status", "deadline", "completed_at", "note"]
    ordering = ["order", "id"]


@admin.register(Project)
class ProjectAdmin(admin.ModelAdmin):
    list_display = ["title", "kind", "series", "owner", "deadline", "status"]
    list_filter = ["kind", "status", "owner"]
    search_fields = ["title", "series", "description"]
    date_hierarchy = "deadline"
    inlines = [StepInline]


@admin.register(StepTemplate)
class StepTemplateAdmin(admin.ModelAdmin):
    list_display = ["kind", "order", "name"]
    list_display_links = ["name"]
    list_editable = ["order"]
    list_filter = ["kind"]
    ordering = ["kind", "order"]
