from django import forms

from tasks.access import projects_visible_to
from tasks.forms import StyledFormMixin

from .models import ApprovalStage, Proposal


class ProposalForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = Proposal
        fields = ["title", "kind", "project", "amount", "attachment"]
        widgets = {"amount": forms.NumberInput(attrs={"min": 0, "step": 1000, "placeholder": "VD: 25000000"})}

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["project"].queryset = projects_visible_to(user).order_by("title")
        self.fields["project"].empty_label = "— Không thuộc đầu việc nào —"
        if self.instance.pk:
            # File đính kèm được thay ở trang chi tiết.
            del self.fields["attachment"]


class AttachmentForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = Proposal
        fields = ["attachment"]
        widgets = {"attachment": forms.FileInput()}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["attachment"].required = True


class StageForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = ApprovalStage
        fields = ["department", "signer_name"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["department"].widget.attrs["placeholder"] = "Phòng / đơn vị"
        self.fields["signer_name"].widget.attrs["placeholder"] = "Người ký (VD: Trưởng phòng)"


class StageEditForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = ApprovalStage
        fields = ["department", "signer_name", "note"]
