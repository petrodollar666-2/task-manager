from django.contrib import admin

from .models import Absence, TeachingSlot


@admin.register(TeachingSlot)
class TeachingSlotAdmin(admin.ModelAdmin):
    list_display = ("teacher", "weekday", "start_time", "end_time", "course", "room",
                    "term_start", "term_end")
    list_filter = ("weekday", "teacher", "term_start", "term_end")
    search_fields = ("course", "room", "teacher__full_name", "teacher__username")
    list_select_related = ("teacher",)
    autocomplete_fields = ("teacher",)


@admin.register(Absence)
class AbsenceAdmin(admin.ModelAdmin):
    list_display = ("user", "kind", "start", "end", "note")
    list_filter = ("kind", "user", "start")
    search_fields = ("note", "user__full_name", "user__username")
    list_select_related = ("user",)
    autocomplete_fields = ("user",)
    date_hierarchy = "start"
