from django import forms

from approvals.models import Proposal
from tasks.models import Project

from .models import Document

INPUT_CLASS = (
    "block w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm "
    "shadow-sm focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500"
)
FILE_CLASS = (
    "block w-full text-sm text-slate-600 file:mr-3 file:rounded file:border-0 "
    "file:bg-indigo-50 file:px-3 file:py-2 file:text-indigo-700 hover:file:bg-indigo-100"
)
MAX_UPLOAD_MB = 100


def projects_for(user):
    qs = Project.objects.all() if user.is_boss else Project.objects.filter(owner=user)
    return qs.order_by("title")


def proposals_for(user):
    qs = Proposal.objects.all() if user.is_boss else Proposal.objects.filter(owner=user)
    return qs.order_by("-created_at")


class DocumentForm(forms.ModelForm):
    class Meta:
        model = Document
        fields = ["file", "name", "description", "project", "proposal"]
        labels = {
            "file": "Chọn file",
            "name": "Tên tài liệu",
            "description": "Mô tả",
            "project": "Thuộc đầu việc",
            "proposal": "Thuộc tờ trình",
        }
        help_texts = {
            "file": "Hỗ trợ trích xuất nội dung để tìm kiếm: PDF, Word (.docx), Excel (.xlsx), TXT, CSV, MD.",
            "name": "Để trống sẽ dùng tên file.",
        }
        widgets = {
            "file": forms.ClearableFileInput(attrs={"class": FILE_CLASS}),
            "name": forms.TextInput(attrs={"class": INPUT_CLASS}),
            "description": forms.Textarea(attrs={"class": INPUT_CLASS, "rows": 3}),
            "project": forms.Select(attrs={"class": INPUT_CLASS}),
            "proposal": forms.Select(attrs={"class": INPUT_CLASS}),
        }

    def __init__(self, *args, user, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user
        self.fields["name"].required = False
        self.fields["project"].queryset = projects_for(user)
        self.fields["proposal"].queryset = proposals_for(user)
        self.fields["project"].empty_label = "— Không gắn —"
        self.fields["proposal"].empty_label = "— Không gắn —"
        # Giữ lựa chọn hiện có khi sửa dù người sửa (sếp/owner) không còn quyền với nó.
        if self.instance.pk:
            if self.instance.project_id:
                self.fields["project"].queryset = (
                    self.fields["project"].queryset
                    | Project.objects.filter(pk=self.instance.project_id)
                ).distinct()
            if self.instance.proposal_id:
                self.fields["proposal"].queryset = (
                    self.fields["proposal"].queryset
                    | Proposal.objects.filter(pk=self.instance.proposal_id)
                ).distinct()
            self.fields["file"].label = "Thay file mới (không bắt buộc)"
            self.fields["file"].widget = forms.FileInput(attrs={"class": FILE_CLASS})
        else:
            self.fields["file"].required = True
            self.fields["file"].widget = forms.FileInput(attrs={"class": FILE_CLASS})

    def clean_file(self):
        f = self.cleaned_data.get("file")
        if f and hasattr(f, "size") and f.size > MAX_UPLOAD_MB * 1024 * 1024:
            raise forms.ValidationError(f"File quá lớn (tối đa {MAX_UPLOAD_MB} MB).")
        return f

    def clean(self):
        cleaned = super().clean()
        if not cleaned.get("name"):
            f = cleaned.get("file")
            if f is not None and getattr(f, "name", None):
                cleaned["name"] = f.name.rsplit("/", 1)[-1][:255]
            elif self.instance.pk:
                cleaned["name"] = self.instance.name
            else:
                self.add_error("name", "Vui lòng nhập tên tài liệu.")
        return cleaned


class SearchForm(forms.Form):
    q = forms.CharField(
        required=False,
        max_length=200,
        widget=forms.TextInput(attrs={
            "class": INPUT_CLASS + " pl-10",
            "placeholder": "Tìm theo tên, mô tả hoặc nội dung… (gõ không dấu cũng được)",
            "autocomplete": "off",
            "autofocus": True,
            "type": "search",
        }),
    )
    source = forms.ChoiceField(
        required=False,
        choices=[("", "Mọi nguồn")] + list(Document.Source.choices),
        widget=forms.Select(attrs={"class": INPUT_CLASS}),
    )
    project = forms.ModelChoiceField(
        required=False,
        queryset=Project.objects.none(),
        empty_label="Mọi đầu việc",
        widget=forms.Select(attrs={"class": INPUT_CLASS}),
    )

    def __init__(self, *args, user, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["project"].queryset = projects_for(user)
