from django import forms
from django.contrib.auth import get_user_model

from .models import Project, Step

INPUT_CLASS = (
    "block w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm shadow-sm "
    "focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500"
)
CHECKBOX_CLASS = "h-4 w-4 rounded border-slate-300 text-indigo-600 focus:ring-indigo-500"
FILE_CLASS = (
    "block w-full text-sm text-slate-600 file:mr-3 file:rounded file:border-0 file:bg-indigo-50 "
    "file:px-3 file:py-2 file:text-sm file:font-medium file:text-indigo-700 hover:file:bg-indigo-100"
)


class DateInput(forms.DateInput):
    input_type = "date"

    def __init__(self, attrs=None):
        super().__init__(attrs=attrs, format="%Y-%m-%d")


class StyledFormMixin:
    """Gắn class Tailwind cho mọi widget của form."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            widget = field.widget
            if isinstance(widget, forms.CheckboxInput):
                cls = CHECKBOX_CLASS
            elif isinstance(widget, forms.FileInput):
                cls = FILE_CLASS
            else:
                cls = INPUT_CLASS
            if isinstance(widget, forms.Textarea):
                widget.attrs.setdefault("rows", 3)
            widget.attrs["class"] = f"{widget.attrs.get('class', '')} {cls}".strip()


def active_users():
    return get_user_model().objects.filter(is_active=True).order_by("full_name", "username")


class ProjectForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = Project
        fields = ["title", "kind", "series", "owner", "event_date", "deadline", "status", "description"]
        widgets = {
            "event_date": DateInput(),
            "deadline": DateInput(),
            "description": forms.Textarea(attrs={"rows": 4}),
        }

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        if user is not None and user.is_boss:
            self.fields["owner"].queryset = active_users()
            if not self.instance.pk:
                self.fields["owner"].initial = user.pk
        else:
            # Giảng viên: người phụ trách luôn là chính mình (gán trong view).
            del self.fields["owner"]


class StepForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = Step
        fields = ["name", "assignee", "deadline", "status", "order", "note"]
        widgets = {"deadline": DateInput()}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["assignee"].queryset = active_users()
        self.fields["assignee"].empty_label = "— Chưa giao —"


class StepQuickAddForm(StyledFormMixin, forms.ModelForm):
    """Form thêm nhanh bước ngay trên trang chi tiết."""

    class Meta:
        model = Step
        fields = ["name", "assignee", "deadline"]
        widgets = {"deadline": DateInput()}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["assignee"].queryset = active_users()
        self.fields["assignee"].empty_label = "— Chưa giao —"
        self.fields["name"].widget.attrs["placeholder"] = "Tên bước mới…"
