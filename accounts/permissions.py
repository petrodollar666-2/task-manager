from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin


class BossRequiredMixin(LoginRequiredMixin, UserPassesTestMixin):
    """Chỉ sếp (role=admin hoặc superuser) được truy cập."""

    def test_func(self):
        return self.request.user.is_boss


def visible_to(user, queryset, owner_field="owner"):
    """Sếp thấy tất cả; giảng viên chỉ thấy bản ghi mà owner_field là chính mình.

    owner_field có thể là đường dẫn lookup, ví dụ "project__owner".
    """
    if user.is_boss:
        return queryset
    return queryset.filter(**{owner_field: user})
