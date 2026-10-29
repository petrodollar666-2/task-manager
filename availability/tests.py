from datetime import date, datetime, time, timedelta, timezone as dt_timezone

import pytest
from django.contrib.auth import get_user_model
from django.urls import NoReverseMatch, reverse
from django.utils import timezone

from approvals.models import ApprovalStage, Proposal
from tasks.models import Project, ProjectKind, Step

from . import services
from .forms import AbsenceForm, TeachingSlotForm
from .models import Absence, TeachingSlot

User = get_user_model()

# Thứ 4, 21/10/2026 lúc 09:00 giờ Việt Nam
NOW = timezone.make_aware(datetime(2026, 10, 21, 9, 0))
TODAY = NOW.date()
TERM_START = date(2026, 9, 1)
TERM_END = date(2026, 12, 31)


def make_user(username, role=User.Role.MEMBER, **kw):
    return User.objects.create_user(username=username, password="x", role=role,
                                    full_name=kw.pop("full_name", username.title()), **kw)


def make_slot(teacher, weekday=None, start=time(8, 0), end=time(10, 0), course="Kinh tế lượng",
              room="A305", term_start=TERM_START, term_end=TERM_END):
    return TeachingSlot.objects.create(
        teacher=teacher, weekday=TODAY.weekday() if weekday is None else weekday,
        start_time=start, end_time=end, course=course, room=room,
        term_start=term_start, term_end=term_end)


def make_absence(user, start=NOW - timedelta(hours=1), end=NOW + timedelta(hours=5),
                 kind=Absence.Kind.BUSINESS_TRIP, note="Hội thảo tại Đà Nẵng"):
    return Absence.objects.create(user=user, kind=kind, start=start, end=end, note=note)


@pytest.fixture
def member(db):
    return make_user("lan", department="Bộ môn Kinh tế")


@pytest.fixture
def other(db):
    return make_user("minh")


@pytest.fixture
def boss(db):
    return make_user("sep", role=User.Role.ADMIN)


def require_integration():
    """Trang tổng quan liên kết tới tasks:detail / approvals:detail của app khác."""
    try:
        reverse("tasks:detail", args=[1])
        reverse("approvals:detail", args=[1])
    except NoReverseMatch:
        pytest.skip("Chưa có URL tasks:detail / approvals:detail (chờ tích hợp)")


# ---------------------------------------------------------------------------
# services.current_status
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestCurrentStatus:
    def test_free_when_nothing(self, member):
        st = services.current_status(member, NOW)
        assert st.code == "free"
        assert st.label == "Rảnh"
        assert st.until is None

    def test_teaching_inside_time(self, member):
        make_slot(member)
        st = services.current_status(member, NOW)
        assert st.code == "teaching"
        assert st.label == "Đang lên lớp"
        assert st.detail == "Kinh tế lượng · Phòng A305"
        assert st.until == time(10, 0)
        assert "10:00" in st.until_text

    def test_teaching_start_inclusive_end_exclusive(self, member):
        make_slot(member)
        at_start = NOW.replace(hour=8, minute=0)
        at_end = NOW.replace(hour=10, minute=0)
        assert services.current_status(member, at_start).code == "teaching"
        assert services.current_status(member, at_end).code == "free"

    def test_outside_time(self, member):
        make_slot(member, start=time(13, 0), end=time(15, 0))
        assert services.current_status(member, NOW).code == "free"

    def test_outside_term(self, member):
        make_slot(member, term_start=date(2026, 1, 1), term_end=date(2026, 6, 30))
        assert services.current_status(member, NOW).code == "free"

    def test_term_boundaries_inclusive(self, member):
        make_slot(member, term_start=TODAY, term_end=TODAY)
        assert services.current_status(member, NOW).code == "teaching"

    def test_wrong_weekday(self, member):
        make_slot(member, weekday=(TODAY.weekday() + 1) % 7)
        assert services.current_status(member, NOW).code == "free"

    def test_uses_local_time(self, member):
        make_slot(member)
        # 02:00 UTC == 09:00 Asia/Ho_Chi_Minh
        utc_now = datetime(2026, 10, 21, 2, 0, tzinfo=dt_timezone.utc)
        assert services.current_status(member, utc_now).code == "teaching"

    def test_absence_takes_precedence(self, member):
        make_slot(member)
        make_absence(member)
        st = services.current_status(member, NOW)
        assert st.code == "absent"
        assert st.label == "Đi công tác"
        assert st.detail == "Hội thảo tại Đà Nẵng"
        assert st.until == NOW + timedelta(hours=5)

    def test_absence_labels_and_fallback_detail(self, member):
        make_absence(member, kind=Absence.Kind.LEAVE, note="")
        st = services.current_status(member, NOW)
        assert st.label == "Nghỉ phép"
        assert st.detail == "Nghỉ phép"

    def test_absence_multi_day_until_text_has_date(self, member):
        make_absence(member, end=NOW + timedelta(days=2))
        st = services.current_status(member, NOW)
        assert "23/10/2026" in st.until_text

    def test_past_absence_ignored(self, member):
        make_slot(member)
        make_absence(member, start=NOW - timedelta(days=2), end=NOW - timedelta(days=1))
        assert services.current_status(member, NOW).code == "teaching"

    def test_absence_end_exclusive(self, member):
        make_absence(member, start=NOW - timedelta(hours=2), end=NOW)
        assert services.current_status(member, NOW).code == "free"

    def test_other_users_data_ignored(self, member, other):
        make_slot(other)
        make_absence(other)
        assert services.current_status(member, NOW).code == "free"


@pytest.mark.django_db
def test_statuses_for_constant_queries(django_assert_max_num_queries):
    users = [make_user(f"gv{i}") for i in range(8)]
    for u in users[:3]:
        make_slot(u)
    for u in users[2:5]:
        make_absence(u)
    with django_assert_max_num_queries(2):
        result = services.statuses_for(users, NOW)
    assert set(result) == {u.pk for u in users}
    codes = [result[u.pk].code for u in users]
    assert codes == ["teaching", "teaching", "absent", "absent", "absent", "free", "free", "free"]


@pytest.mark.django_db
def test_statuses_for_empty():
    assert services.statuses_for([], NOW) == {}


@pytest.mark.django_db
def test_next_slot(member):
    make_slot(member, start=time(7, 0), end=time(8, 30), course="Sáng sớm")
    later = make_slot(member, start=time(13, 0), end=time(15, 0), course="Chiều")
    make_slot(member, start=time(15, 30), end=time(17, 0), course="Muộn")
    make_slot(member, weekday=(TODAY.weekday() + 1) % 7, start=time(10, 0), end=time(11, 0))
    assert services.next_slot(member, NOW) == later
    assert services.next_slot(member, NOW.replace(hour=18)) is None


@pytest.mark.django_db
def test_summarize_project_and_proposal_no_queries(member, django_assert_num_queries):
    p = Project.objects.create(title="Workshop A", kind=ProjectKind.WORKSHOP, owner=member)
    Step.objects.create(project=p, order=1, name="Lên kế hoạch", status=Step.Status.DONE)
    Step.objects.create(project=p, order=2, name="Mời diễn giả", status=Step.Status.DOING)
    Step.objects.create(project=p, order=3, name="Tổ chức")
    Step.objects.create(project=p, order=4, name="Tổng kết")
    pr = Proposal.objects.create(title="Tờ trình kinh phí", owner=member,
                                 status=Proposal.Status.IN_PROGRESS)
    ApprovalStage.objects.create(proposal=pr, order=1, department="Khoa",
                                 status=ApprovalStage.Status.SIGNED)
    ApprovalStage.objects.create(proposal=pr, order=2, department="Phòng KH-TC")
    ApprovalStage.objects.create(proposal=pr, order=3, department="Ban Giám hiệu")

    p = Project.objects.prefetch_related("steps").get(pk=p.pk)
    pr = Proposal.objects.prefetch_related("stages").get(pk=pr.pk)
    with django_assert_num_queries(0):
        services.summarize_project(p)
        services.summarize_proposal(pr)
    assert p.pct == 25
    assert p.cur_step.name == "Mời diễn giả"
    assert (pr.signed, pr.total) == (1, 3)
    assert pr.cur_stage.department == "Phòng KH-TC"


# ---------------------------------------------------------------------------
# Forms
# ---------------------------------------------------------------------------

def slot_data(teacher, **kw):
    data = {"teacher": teacher.pk, "weekday": 0, "start_time": "08:00", "end_time": "10:00",
            "course": "Kinh tế vĩ mô", "room": "B201",
            "term_start": "2026-09-01", "term_end": "2026-12-31"}
    data.update(kw)
    return data


@pytest.mark.django_db
class TestForms:
    def test_slot_end_must_be_after_start(self, member):
        form = TeachingSlotForm(slot_data(member, end_time="07:00"), user=member)
        assert not form.is_valid()
        assert "end_time" in form.errors

    def test_slot_term_order(self, member):
        form = TeachingSlotForm(slot_data(member, term_end="2026-08-01"), user=member)
        assert not form.is_valid()
        assert "term_end" in form.errors

    def test_member_cannot_assign_other_teacher(self, member, other):
        form = TeachingSlotForm(slot_data(other), user=member)
        assert form.is_valid(), form.errors
        assert form.save().teacher == member

    def test_boss_can_pick_teacher(self, boss, other):
        form = TeachingSlotForm(slot_data(other), user=boss)
        assert form.is_valid(), form.errors
        assert form.save().teacher == other

    def test_absence_end_after_start(self, member):
        form = AbsenceForm({"user": member.pk, "kind": "trip", "start": "2026-10-22T08:00",
                            "end": "2026-10-22T08:00", "note": ""}, user=member)
        assert not form.is_valid()
        assert "end" in form.errors

    def test_absence_uses_local_timezone(self, member):
        form = AbsenceForm({"kind": "leave", "start": "2026-10-22T08:00",
                            "end": "2026-10-23T17:00", "note": "Việc gia đình"}, user=member)
        assert form.is_valid(), form.errors
        a = form.save()
        assert a.user == member
        assert timezone.localtime(a.start).hour == 8


# ---------------------------------------------------------------------------
# Schedule views & permissions
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestScheduleViews:
    def test_login_required(self, client):
        resp = client.get(reverse("availability:schedule"))
        assert resp.status_code == 302

    def test_member_sees_only_own(self, client, member, other):
        make_slot(member, course="Môn của Lan", term_start=timezone.localdate() - timedelta(days=30),
                  term_end=timezone.localdate() + timedelta(days=30))
        make_slot(other, course="Môn của Minh", term_start=timezone.localdate() - timedelta(days=30),
                  term_end=timezone.localdate() + timedelta(days=30))
        make_absence(other, start=timezone.now(), end=timezone.now() + timedelta(days=1),
                     note="Chuyến đi của Minh")
        client.force_login(member)
        resp = client.get(reverse("availability:schedule") + f"?teacher={other.pk}")
        html = resp.content.decode()
        assert resp.status_code == 200
        assert "Môn của Lan" in html
        assert "Môn của Minh" not in html
        assert "Chuyến đi của Minh" not in html

    def test_boss_sees_all_and_can_filter(self, client, boss, member, other):
        around = dict(term_start=timezone.localdate() - timedelta(days=30),
                      term_end=timezone.localdate() + timedelta(days=30))
        make_slot(member, course="Môn của Lan", **around)
        make_slot(other, course="Môn của Minh", **around)
        client.force_login(boss)
        html = client.get(reverse("availability:schedule")).content.decode()
        assert "Môn của Lan" in html and "Môn của Minh" in html
        html = client.get(reverse("availability:schedule") + f"?teacher={other.pk}").content.decode()
        assert "Môn của Minh" in html and "Môn của Lan" not in html

    def test_member_cannot_edit_or_delete_others_slot(self, client, member, other):
        slot = make_slot(other)
        client.force_login(member)
        assert client.get(reverse("availability:slot_edit", args=[slot.pk])).status_code == 403
        resp = client.post(reverse("availability:slot_edit", args=[slot.pk]),
                           slot_data(member, course="Hack"))
        assert resp.status_code == 403
        assert client.post(reverse("availability:slot_delete", args=[slot.pk])).status_code == 403
        slot.refresh_from_db()
        assert slot.course == "Kinh tế lượng"

    def test_member_can_edit_and_delete_own_slot(self, client, member):
        slot = make_slot(member)
        client.force_login(member)
        resp = client.post(reverse("availability:slot_edit", args=[slot.pk]),
                           slot_data(member, course="Kinh tế vi mô"))
        assert resp.status_code == 302
        slot.refresh_from_db()
        assert slot.course == "Kinh tế vi mô"
        assert client.get(reverse("availability:slot_delete", args=[slot.pk])).status_code == 200
        assert client.post(reverse("availability:slot_delete", args=[slot.pk])).status_code == 302
        assert not TeachingSlot.objects.filter(pk=slot.pk).exists()

    def test_boss_can_edit_and_delete_any_slot(self, client, boss, other):
        slot = make_slot(other)
        client.force_login(boss)
        assert client.get(reverse("availability:slot_edit", args=[slot.pk])).status_code == 200
        resp = client.post(reverse("availability:slot_edit", args=[slot.pk]),
                           slot_data(other, course="Đổi môn"))
        assert resp.status_code == 302
        slot.refresh_from_db()
        assert slot.course == "Đổi môn"
        assert client.post(reverse("availability:slot_delete", args=[slot.pk])).status_code == 302
        assert not TeachingSlot.objects.exists()

    def test_member_create_slot_forced_to_self(self, client, member, other):
        client.force_login(member)
        assert client.get(reverse("availability:slot_create")).status_code == 200
        resp = client.post(reverse("availability:slot_create"), slot_data(other))
        assert resp.status_code == 302
        assert TeachingSlot.objects.get().teacher == member

    def test_create_slot_invalid_shows_error(self, client, member):
        client.force_login(member)
        resp = client.post(reverse("availability:slot_create"),
                           slot_data(member, end_time="07:00"))
        assert resp.status_code == 200
        assert "Giờ kết thúc phải sau giờ bắt đầu" in resp.content.decode()
        assert not TeachingSlot.objects.exists()

    def test_absence_permissions(self, client, member, other, boss):
        a = make_absence(other)
        client.force_login(member)
        assert client.get(reverse("availability:absence_edit", args=[a.pk])).status_code == 403
        assert client.post(reverse("availability:absence_delete", args=[a.pk])).status_code == 403
        assert Absence.objects.filter(pk=a.pk).exists()
        client.force_login(boss)
        assert client.get(reverse("availability:absence_edit", args=[a.pk])).status_code == 200
        assert client.post(reverse("availability:absence_delete", args=[a.pk])).status_code == 302
        assert not Absence.objects.filter(pk=a.pk).exists()

    def test_member_create_absence(self, client, member, other):
        client.force_login(member)
        assert client.get(reverse("availability:absence_create")).status_code == 200
        resp = client.post(reverse("availability:absence_create"), {
            "user": other.pk, "kind": "trip", "start": "2026-11-01T08:00",
            "end": "2026-11-03T17:00", "note": "Công tác Huế"})
        assert resp.status_code == 302
        assert Absence.objects.get().user == member

    def test_status_table_boss_only(self, client, member):
        client.force_login(member)
        assert client.get(reverse("availability:status_table")).status_code == 403


# ---------------------------------------------------------------------------
# Dashboard (cần các app tasks/approvals đã có URL chi tiết)
# ---------------------------------------------------------------------------

@pytest.fixture
def dashboard_data(boss, member, other):
    today = timezone.localdate()
    p = Project.objects.create(title="Workshop Kinh tế số", kind=ProjectKind.WORKSHOP,
                               owner=member, event_date=today + timedelta(days=10),
                               deadline=today + timedelta(days=20))
    Step.objects.create(project=p, order=1, name="Lập kế hoạch", status=Step.Status.DONE,
                        assignee=member)
    Step.objects.create(project=p, order=2, name="Mời diễn giả", assignee=other,
                        deadline=today - timedelta(days=2))
    p2 = Project.objects.create(title="Working paper 01", kind=ProjectKind.WORKING_PAPER,
                                owner=other)
    Step.objects.create(project=p2, order=1, name="Viết bản thảo", assignee=other)
    pr = Proposal.objects.create(title="Tờ trình kinh phí workshop", owner=member,
                                 status=Proposal.Status.IN_PROGRESS)
    ApprovalStage.objects.create(proposal=pr, order=1, department="Khoa",
                                 status=ApprovalStage.Status.SIGNED)
    ApprovalStage.objects.create(proposal=pr, order=2, department="Phòng Kế hoạch - Tài chính")
    now = timezone.localtime()
    TeachingSlot.objects.create(teacher=member, weekday=now.weekday(), start_time=time(0, 0),
                                end_time=time(23, 59, 59), course="Kinh tế lượng", room="A305",
                                term_start=today, term_end=today)
    return {"project": p, "proposal": pr}


@pytest.mark.django_db
class TestDashboard:
    def test_login_required(self, client):
        assert client.get(reverse("dashboard")).status_code == 302

    def test_boss_dashboard(self, client, boss, dashboard_data, django_assert_max_num_queries):
        require_integration()
        client.force_login(boss)
        with django_assert_max_num_queries(15):
            resp = client.get(reverse("dashboard"))
        assert resp.status_code == 200
        html = resp.content.decode()
        assert "Ai đang làm gì" in html
        assert "Đang lên lớp" in html
        assert "Kinh tế lượng · Phòng A305" in html
        assert "Workshop Kinh tế số" in html
        assert "Mời diễn giả" in html
        assert "Phòng Kế hoạch - Tài chính" in html
        assert "Đã ký 1/2" in html
        assert resp.context["stats"]["teaching_now"] == 1
        assert resp.context["stats"]["proposals_in_progress"] == 1
        rows = {r["user"].username: r for r in resp.context["rows"]}
        assert "sep" not in rows
        assert rows["minh"]["overdue"] == 1
        assert {p.title for p in rows["minh"]["projects"]} == {
            "Workshop Kinh tế số", "Working paper 01"}

    def test_boss_dashboard_queries_do_not_grow(self, client, boss, dashboard_data,
                                                django_assert_max_num_queries):
        require_integration()
        for i in range(10):
            u = make_user(f"extra{i}")
            proj = Project.objects.create(title=f"Dự án {i}", owner=u)
            Step.objects.create(project=proj, order=1, name="Bước 1", assignee=u)
            make_slot(u, weekday=timezone.localdate().weekday())
        client.force_login(boss)
        with django_assert_max_num_queries(15):
            assert client.get(reverse("dashboard")).status_code == 200

    def test_status_table_partial(self, client, boss, dashboard_data):
        require_integration()
        client.force_login(boss)
        resp = client.get(reverse("availability:status_table"))
        assert resp.status_code == 200
        assert 'hx-trigger="every 60s"' in resp.content.decode()

    def test_member_dashboard(self, client, member, dashboard_data):
        require_integration()
        client.force_login(member)
        resp = client.get(reverse("dashboard"))
        assert resp.status_code == 200
        html = resp.content.decode()
        assert "Trạng thái của tôi" in html
        assert "Đang lên lớp" in html
        assert "Workshop Kinh tế số" in html
        assert "Tờ trình kinh phí workshop" in html
        assert "Phòng Kế hoạch - Tài chính" in html
        assert "Ai đang làm gì" not in html
