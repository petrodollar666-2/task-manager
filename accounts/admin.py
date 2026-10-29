from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import User


@admin.register(User)
class CustomUserAdmin(UserAdmin):
    list_display = ("username", "full_name", "role", "department", "is_active")
    list_filter = ("role", "is_active")
    fieldsets = UserAdmin.fieldsets + (
        ("Thông tin khoa", {"fields": ("full_name", "role", "department")}),
    )
    add_fieldsets = UserAdmin.add_fieldsets + (
        ("Thông tin khoa", {"fields": ("full_name", "role", "department")}),
    )
