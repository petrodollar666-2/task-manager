from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    class Role(models.TextChoices):
        ADMIN = "admin", "Quản lý (Sếp)"
        MEMBER = "member", "Giảng viên"

    full_name = models.CharField("Họ và tên", max_length=150, blank=True)
    role = models.CharField("Vai trò", max_length=10, choices=Role.choices, default=Role.MEMBER)
    department = models.CharField("Bộ môn", max_length=150, blank=True)

    class Meta:
        verbose_name = "Người dùng"
        verbose_name_plural = "Người dùng"
        ordering = ["full_name", "username"]

    @property
    def is_boss(self):
        return self.is_superuser or self.role == self.Role.ADMIN

    def __str__(self):
        return self.full_name or self.username
