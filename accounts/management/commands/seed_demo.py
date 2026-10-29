"""Tạo tài khoản và dữ liệu mẫu để dùng thử.

    python manage.py seed_demo          # thêm dữ liệu mẫu (bỏ qua nếu đã có)
    python manage.py seed_demo --reset  # xóa dữ liệu nghiệp vụ rồi tạo lại
"""
from datetime import datetime, time, timedelta

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from accounts.models import User
from approvals.models import ApprovalRouteTemplate, ApprovalStage, Proposal
from availability.models import Absence, TeachingSlot
from files.models import Document
from tasks.models import Project, ProjectKind, Step, StepTemplate

TEACHERS = [
    ("giaovien1", "TS. Nguyễn Văn An", "Bộ môn Kinh tế học"),
    ("giaovien2", "PGS.TS. Trần Thị Bình", "Bộ môn Tài chính"),
    ("giaovien3", "TS. Lê Minh Châu", "Bộ môn Kinh tế quốc tế"),
    ("giaovien4", "ThS. Phạm Thu Dung", "Bộ môn Kinh tế học"),
]

FALLBACK_STEPS = {
    ProjectKind.WORKSHOP: ["Chốt chủ đề & thời gian", "Lập tờ trình & dự toán", "Mời diễn giả / khách mời",
                           "Truyền thông & đăng ký", "Tổ chức workshop", "Báo cáo tổng kết & quyết toán"],
    ProjectKind.WORKING_PAPER: ["Bản thảo", "Góp ý nội bộ", "Phản biện", "Chỉnh sửa theo phản biện",
                                "Biên tập & dàn trang", "Công bố trong series"],
    ProjectKind.OTHER: ["Lập kế hoạch", "Thực hiện", "Báo cáo"],
}

FALLBACK_ROUTE = [
    ("Bộ môn / Khoa", "Trưởng khoa"),
    ("Phòng Quản lý Khoa học", "Trưởng phòng QLKH"),
    ("Phòng Kế hoạch – Tài chính", "Trưởng phòng KH-TC"),
    ("Ban Giám hiệu", "Phó Hiệu trưởng phụ trách"),
]


def make_user(username, password, full_name, role, department="", boss=False):
    user, _ = User.objects.get_or_create(username=username)
    user.full_name = full_name
    user.role = role
    user.department = department
    user.is_staff = boss
    user.is_superuser = boss
    user.set_password(password)
    user.save()
    return user


def step_names(kind):
    names = list(StepTemplate.objects.filter(kind=kind).order_by("order").values_list("name", flat=True))
    return names or FALLBACK_STEPS[kind]


def route(kind):
    rows = list(ApprovalRouteTemplate.objects.filter(kind=kind).order_by("order")
                .values_list("department", "signer_name"))
    return rows or FALLBACK_ROUTE


class Command(BaseCommand):
    help = "Tạo tài khoản admin/admin, giaovien1..4 và dữ liệu mẫu"

    def add_arguments(self, parser):
        parser.add_argument("--reset", action="store_true", help="Xóa dữ liệu nghiệp vụ cũ trước khi tạo")

    @transaction.atomic
    def handle(self, *args, **opts):
        boss = make_user("admin", "admin", "Trưởng khoa (Sếp)", User.Role.ADMIN, "Ban chủ nhiệm khoa", boss=True)
        teachers = [make_user(u, u, name, User.Role.MEMBER, dept) for u, name, dept in TEACHERS]
        self.stdout.write("Tài khoản: admin/admin (sếp); " + ", ".join(f"{u}/{u}" for u, _, _ in TEACHERS))

        if opts["reset"]:
            Document.objects.all().delete()
            Proposal.objects.all().delete()
            Project.objects.all().delete()
            TeachingSlot.objects.all().delete()
            Absence.objects.all().delete()
        elif Project.objects.exists():
            self.stdout.write("Đã có dữ liệu, bỏ qua phần dữ liệu mẫu (dùng --reset để tạo lại).")
            return

        today = timezone.localdate()
        gv1, gv2, gv3, gv4 = teachers

        projects = {}

        def project(key, title, kind, owner, done_steps, deadline_days, event_days=None, series=""):
            p = Project.objects.create(
                title=title, kind=kind, owner=owner, series=series,
                deadline=today + timedelta(days=deadline_days),
                event_date=today + timedelta(days=event_days) if event_days is not None else None,
            )
            names = step_names(kind)
            for i, name in enumerate(names, start=1):
                if i <= done_steps:
                    status = Step.Status.DONE
                elif i == done_steps + 1:
                    status = Step.Status.DOING
                else:
                    status = Step.Status.TODO
                Step.objects.create(
                    project=p, order=i, name=name, assignee=owner, status=status,
                    deadline=today + timedelta(days=deadline_days * i // len(names) - 3),
                    completed_at=timezone.now() if status == Step.Status.DONE else None,
                )
            if done_steps >= len(names):
                p.status = Project.Status.DONE
                p.save()
            projects[key] = p
            return p

        project("ws1", "Workshop: Chuyển đổi số trong giáo dục đại học", ProjectKind.WORKSHOP, gv1, 2, 25, 20)
        project("ws2", "Workshop: Kinh tế xanh và phát triển bền vững", ProjectKind.WORKSHOP, gv3, 1, 50, 45)
        series = "FTU Working Paper Series 2026"
        project("wp1", "WP 2026-01: Tác động của FDI đến năng suất lao động", ProjectKind.WORKING_PAPER, gv1, 3, 40,
                series=series)
        project("wp2", "WP 2026-02: Rủi ro tín dụng ngân hàng thương mại Việt Nam", ProjectKind.WORKING_PAPER, gv2,
                4, 15, series=series)
        project("wp3", "WP 2026-03: Thương mại điện tử xuyên biên giới", ProjectKind.WORKING_PAPER, gv3, 1, -5,
                series=series)
        project("wp4", "WP 2026-04: Lạm phát và chính sách tiền tệ", ProjectKind.WORKING_PAPER, gv4, 6, -10,
                series=series)
        project("ot1", "Cập nhật đề cương học phần Kinh tế vi mô", ProjectKind.OTHER, gv4, 1, 12)

        def proposal(title, kind, owner, project_key, signed, amount=None, days_ago=7):
            p = Proposal.objects.create(
                title=title, kind=kind, owner=owner, project=projects.get(project_key), amount=amount,
                submitted_at=today - timedelta(days=days_ago) if signed is not None else None,
            )
            for i, (dept, signer) in enumerate(route(kind), start=1):
                is_signed = signed is not None and i <= signed
                ApprovalStage.objects.create(
                    proposal=p, order=i, department=dept, signer_name=signer,
                    status=ApprovalStage.Status.SIGNED if is_signed else ApprovalStage.Status.PENDING,
                    signed_at=timezone.now() - timedelta(days=days_ago - i) if is_signed else None,
                )
            p.refresh_status()
            return p

        proposal("Tờ trình tổ chức Workshop Chuyển đổi số", Proposal.Kind.PROPOSAL, gv1, "ws1", 2)
        proposal("Dự toán kinh phí Workshop Chuyển đổi số", Proposal.Kind.FINANCE, gv1, "ws1", 1, 85_000_000)
        proposal("Kế hoạch tài chính Working Paper Series 2026", Proposal.Kind.FINANCE, gv2, None, 5, 120_000_000, 20)
        proposal("Tờ trình mời chuyên gia quốc tế - Workshop Kinh tế xanh", Proposal.Kind.PROPOSAL, gv3, "ws2", None)

        # Lịch dạy: học kỳ hiện tại, có một buổi đang diễn ra lúc tạo dữ liệu để thấy trạng thái "Đang lên lớp".
        term_start, term_end = today - timedelta(days=45), today + timedelta(days=75)
        now_local = timezone.localtime()
        cur_start = time(max(now_local.hour - 1, 0), 0)
        cur_end = time(min(now_local.hour + 2, 23), 0)
        wd = today.weekday()
        slots = [
            (gv1, (wd + 1) % 7, time(7, 0), time(9, 30), "Kinh tế vi mô", "A305"),
            (gv1, (wd + 3) % 7, time(13, 0), time(15, 30), "Kinh tế lượng", "B204"),
            (gv2, wd, cur_start, cur_end, "Tài chính doanh nghiệp", "A201"),
            (gv2, (wd + 2) % 7, time(9, 45), time(12, 0), "Thị trường tài chính", "C102"),
            (gv3, (wd + 1) % 7, time(13, 0), time(15, 30), "Kinh tế quốc tế", "A402"),
            (gv4, wd, time(7, 0), time(9, 30) if now_local.hour >= 10 else time(6, 0), "Kinh tế vĩ mô", "B105"),
            (gv4, (wd + 4) % 7, time(9, 45), time(12, 0), "Nguyên lý kinh tế", "B105"),
        ]
        for teacher, weekday, start, end, course, room in slots:
            if end <= start:
                continue
            TeachingSlot.objects.create(teacher=teacher, weekday=weekday, start_time=start, end_time=end,
                                        course=course, room=room, term_start=term_start, term_end=term_end)

        tz = timezone.get_current_timezone()
        Absence.objects.create(
            user=gv3, kind=Absence.Kind.BUSINESS_TRIP,
            start=timezone.make_aware(datetime.combine(today - timedelta(days=1), time(8, 0)), tz),
            end=timezone.make_aware(datetime.combine(today + timedelta(days=2), time(17, 0)), tz),
            note="Hội thảo khoa học tại Đà Nẵng",
        )

        self._seed_documents(boss, gv1, gv2, projects)
        self.stdout.write(self.style.SUCCESS("Đã tạo dữ liệu mẫu."))

    def _seed_documents(self, boss, gv1, gv2, projects):
        """Tạo vài tài liệu dạng text để thử tìm kiếm."""
        from django.core.files.base import ContentFile

        docs = [
            (gv1, "ws1", "Kế hoạch tổ chức workshop chuyển đổi số.txt",
             "Kế hoạch tổ chức workshop Chuyển đổi số trong giáo dục đại học. Thời gian: tháng 11. "
             "Diễn giả: chuyên gia từ Bộ Giáo dục và Đào tạo. Dự kiến 120 đại biểu."),
            (gv1, "wp1", "Bản thảo WP FDI và năng suất.txt",
             "Nghiên cứu tác động của đầu tư trực tiếp nước ngoài (FDI) đến năng suất lao động "
             "tại các doanh nghiệp sản xuất Việt Nam giai đoạn 2010-2024."),
            (gv2, "wp2", "Số liệu rủi ro tín dụng.txt",
             "Bộ số liệu nợ xấu và rủi ro tín dụng của 27 ngân hàng thương mại Việt Nam, nguồn báo cáo thường niên."),
            (boss, None, "Quy chế chi tiêu nội bộ 2026.txt",
             "Quy chế chi tiêu nội bộ: định mức chi hội thảo, workshop, thù lao báo cáo viên, chi phí in ấn, "
             "kế hoạch tài chính năm 2026 của khoa."),
        ]
        for owner, project_key, name, text in docs:
            doc = Document(name=name, owner=owner, project=projects.get(project_key), original_filename=name,
                           description=text[:120], mime_type="text/plain")
            doc.file.save(name, ContentFile(text.encode("utf-8")), save=True)
            doc.reextract()
