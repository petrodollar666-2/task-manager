from django import forms
from django.contrib.auth import get_user_model

from .models import Absence, TeachingSlot

INPUT_CLASS = (
    "block w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm "
    "shadow-sm focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500"
)


class StyledOwnerForm(forms.ModelForm):
    """ModelForm có input đã gắn class Tailwind và trường chủ sở hữu tự khoá.

    - Sếp: được chọn bất kỳ người dùng nào.
    - Giảng viên: trường chủ sở hữu bị ẩn và luôn bị gán là chính mình.
    """

    owner_field = None

    def __init__(self, *args, user, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)
        for f in self.fields.values():
            f.widget.attrs.setdefault("class", INPUT_CLASS)
        owner = self.fields[self.owner_field]
        if user.is_boss:
            owner.queryset = get_user_model().objects.filter(is_active=True)
            owner.label_from_instance = (
                lambda u: f"{u} ({u.department})" if u.department else str(u)
            )
        else:
            owner.queryset = get_user_model().objects.filter(pk=user.pk)
            owner.widget = forms.HiddenInput()
            # disabled: bỏ qua giá trị gửi lên, luôn dùng giá trị ban đầu (chính mình)
            owner.disabled = True
            self.initial[self.owner_field] = user.pk

    def clean(self):
        cleaned = super().clean()
        if not self.user.is_boss:
            cleaned[self.owner_field] = self.user
        return cleaned


class TeachingSlotForm(StyledOwnerForm):
    owner_field = "teacher"

    class Meta:
        model = TeachingSlot
        fields = ["teacher", "weekday", "start_time", "end_time", "course", "room",
                  "term_start", "term_end"]
        widgets = {
            "start_time": forms.TimeInput(attrs={"type": "time"}, format="%H:%M"),
            "end_time": forms.TimeInput(attrs={"type": "time"}, format="%H:%M"),
            "term_start": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
            "term_end": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
            "course": forms.TextInput(attrs={"placeholder": "Ví dụ: Kinh tế lượng"}),
            "room": forms.TextInput(attrs={"placeholder": "Ví dụ: A305"}),
        }

    def clean(self):
        cleaned = super().clean()
        start, end = cleaned.get("start_time"), cleaned.get("end_time")
        if start and end and end <= start:
            self.add_error("end_time", "Giờ kết thúc phải sau giờ bắt đầu.")
        ts, te = cleaned.get("term_start"), cleaned.get("term_end")
        if ts and te and te < ts:
            self.add_error("term_end", "Ngày kết thúc học kỳ phải sau ngày bắt đầu.")
        return cleaned


class AbsenceForm(StyledOwnerForm):
    owner_field = "user"

    class Meta:
        model = Absence
        fields = ["user", "kind", "start", "end", "note"]
        widgets = {
            "start": forms.DateTimeInput(attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M"),
            "end": forms.DateTimeInput(attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M"),
            "note": forms.TextInput(attrs={"placeholder": "Ví dụ: Hội thảo tại Đà Nẵng"}),
        }

    def clean(self):
        cleaned = super().clean()
        start, end = cleaned.get("start"), cleaned.get("end")
        if start and end and end <= start:
            self.add_error("end", "Thời điểm kết thúc phải sau thời điểm bắt đầu.")
        return cleaned
