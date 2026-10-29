from django.conf import settings
from django.db import models


class TeachingSlot(models.Model):
    """Một buổi dạy lặp lại hằng tuần trong học kỳ."""

    class Weekday(models.IntegerChoices):
        MON = 0, "Thứ 2"
        TUE = 1, "Thứ 3"
        WED = 2, "Thứ 4"
        THU = 3, "Thứ 5"
        FRI = 4, "Thứ 6"
        SAT = 5, "Thứ 7"
        SUN = 6, "Chủ nhật"

    teacher = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                                related_name="teaching_slots", verbose_name="Giảng viên")
    weekday = models.IntegerField("Thứ", choices=Weekday.choices)  # 0 = Thứ 2 (date.weekday())
    start_time = models.TimeField("Bắt đầu")
    end_time = models.TimeField("Kết thúc")
    course = models.CharField("Môn học", max_length=255)
    room = models.CharField("Phòng học", max_length=50, blank=True)
    term_start = models.DateField("Học kỳ từ ngày")
    term_end = models.DateField("Học kỳ đến ngày")

    class Meta:
        verbose_name = "Lịch dạy"
        verbose_name_plural = "Lịch dạy"
        ordering = ["teacher", "weekday", "start_time"]

    def __str__(self):
        return f"{self.teacher} - {self.get_weekday_display()} {self.start_time:%H:%M} {self.course}"


class Absence(models.Model):
    """Công tác, nghỉ phép... trong một khoảng thời gian."""

    class Kind(models.TextChoices):
        BUSINESS_TRIP = "trip", "Đi công tác"
        LEAVE = "leave", "Nghỉ phép"
        MEETING = "meeting", "Họp / sự kiện"
        OTHER = "other", "Khác"

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                             related_name="absences", verbose_name="Giảng viên")
    kind = models.CharField("Loại", max_length=10, choices=Kind.choices, default=Kind.BUSINESS_TRIP)
    start = models.DateTimeField("Từ")
    end = models.DateTimeField("Đến")
    note = models.CharField("Ghi chú", max_length=255, blank=True)

    class Meta:
        verbose_name = "Vắng mặt"
        verbose_name_plural = "Vắng mặt"
        ordering = ["-start"]

    def __str__(self):
        return f"{self.user} - {self.get_kind_display()}"
