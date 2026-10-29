from django.contrib import admin

from .models import ApprovalRouteTemplate, ApprovalStage, Proposal
from .services import recompute_status


class ApprovalStageInline(admin.TabularInline):
    model = ApprovalStage
    extra = 0
    fields = ["order", "department", "signer_name", "status", "signed_at", "note"]
    ordering = ["order", "id"]


@admin.register(Proposal)
class ProposalAdmin(admin.ModelAdmin):
    list_display = ["title", "kind", "owner", "project", "amount", "status", "submitted_at"]
    list_filter = ["kind", "status", "owner"]
    search_fields = ["title"]
    inlines = [ApprovalStageInline]

    def save_related(self, request, form, formsets, change):
        super().save_related(request, form, formsets, change)
        recompute_status(form.instance)


@admin.register(ApprovalRouteTemplate)
class ApprovalRouteTemplateAdmin(admin.ModelAdmin):
    list_display = ["kind", "order", "department", "signer_name"]
    list_display_links = ["department"]
    list_editable = ["order"]
    list_filter = ["kind"]
    ordering = ["kind", "order"]
