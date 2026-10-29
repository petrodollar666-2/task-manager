import pytest
from django.urls import reverse

from accounts.models import User
from tasks.access import projects_visible_to
from tasks.models import Project, ProjectKind, Step, StepTemplate
from tasks.services import create_steps_from_templates

pytestmark = pytest.mark.django_db


@pytest.fixture
def boss():
    return User.objects.create_user("sep", password="x", full_name="Sếp", role=User.Role.ADMIN)


@pytest.fixture
def alice():
    return User.objects.create_user("alice", password="x", full_name="Alice", role=User.Role.MEMBER)


@pytest.fixture
def bob():
    return User.objects.create_user("bob", password="x", full_name="Bob", role=User.Role.MEMBER)


@pytest.fixture
def project(alice):
    p = Project.objects.create(title="Workshop AI", kind=ProjectKind.WORKSHOP, owner=alice)
    create_steps_from_templates(p)
    return p


def login(client, user):
    client.force_login(user)
    return client


# ------------------------------------------------------------- seed & generation

def test_seeded_step_templates():
    ws = list(StepTemplate.objects.filter(kind="workshop").values_list("name", flat=True))
    wp = list(StepTemplate.objects.filter(kind="working_paper").values_list("name", flat=True))
    assert ws[0] == "Chốt chủ đề & thời gian"
    assert ws[-1] == "Báo cáo tổng kết & quyết toán"
    assert len(ws) == 6
    assert wp == ["Bản thảo", "Góp ý nội bộ", "Phản biện", "Chỉnh sửa theo phản biện",
                  "Biên tập & dàn trang", "Công bố trong series"]


def test_steps_generated_from_templates(project):
    names = list(project.steps.order_by("order").values_list("name", flat=True))
    expected = list(StepTemplate.objects.filter(kind="workshop").order_by("order").values_list("name", flat=True))
    assert names == expected
    assert list(project.steps.order_by("order").values_list("order", flat=True)) == [1, 2, 3, 4, 5, 6]


def test_create_view_generates_steps_and_forces_owner_for_member(client, alice, bob):
    login(client, alice)
    resp = client.post(reverse("tasks:create"), {
        "title": "WP 01", "kind": "working_paper", "status": "active", "owner": bob.pk,
    })
    assert resp.status_code == 302
    p = Project.objects.get(title="WP 01")
    assert p.owner == alice  # giảng viên không chọn được người khác
    assert p.steps.count() == 6
    assert p.current_step.name == "Bản thảo"


def test_boss_can_choose_owner(client, boss, bob):
    login(client, boss)
    client.post(reverse("tasks:create"), {"title": "Việc khác", "kind": "other", "status": "active",
                                          "owner": bob.pk})
    p = Project.objects.get(title="Việc khác")
    assert p.owner == bob
    assert p.steps.count() == 0  # loại "Khác" không có bước mẫu


# ------------------------------------------------------------- progress

def test_progress_and_current_step(project):
    steps = list(project.steps.order_by("order"))
    assert project.progress == 0
    assert project.current_step == steps[0]
    for s in steps[:3]:
        s.status = Step.Status.DONE
        s.save()
    assert project.progress == 50
    assert project.current_step == steps[3]
    project.steps.update(status=Step.Status.DONE)
    assert project.progress == 100
    assert project.current_step is None


def test_progress_without_steps(alice):
    p = Project.objects.create(title="Trống", owner=alice)
    assert p.progress == 0
    p.status = Project.Status.DONE
    assert p.progress == 100


# ------------------------------------------------------------- permissions

def test_member_cannot_view_other_members_project(client, project, bob):
    login(client, bob)
    assert client.get(reverse("tasks:detail", args=[project.pk])).status_code == 404
    assert client.get(reverse("tasks:edit", args=[project.pk])).status_code == 404
    resp = client.get(reverse("tasks:list"))
    assert project.title not in resp.content.decode()


def test_owner_and_boss_can_view(client, project, alice, boss):
    login(client, alice)
    assert client.get(reverse("tasks:detail", args=[project.pk])).status_code == 200
    client.logout()
    login(client, boss)
    resp = client.get(reverse("tasks:detail", args=[project.pk]))
    assert resp.status_code == 200
    assert "Chốt chủ đề" in resp.content.decode()
    assert client.get(reverse("tasks:edit", args=[project.pk])).status_code == 200
    assert project.title in client.get(reverse("tasks:list")).content.decode()


def test_assignee_can_view_but_not_edit(client, project, bob):
    step = project.steps.order_by("order")[1]
    step.assignee = bob
    step.save()
    assert project in projects_visible_to(bob)
    login(client, bob)
    assert client.get(reverse("tasks:detail", args=[project.pk])).status_code == 200
    assert client.get(reverse("tasks:edit", args=[project.pk])).status_code == 403
    assert client.post(reverse("tasks:step_add", args=[project.pk]), {"name": "X"}).status_code == 403
    assert project.title in client.get(reverse("tasks:list")).content.decode()


def test_assignee_can_change_only_own_step(client, project, bob):
    own, other = project.steps.order_by("order")[:2]
    own.assignee = bob
    own.save()
    login(client, bob)
    resp = client.post(reverse("tasks:step_status", args=[own.pk]), {"status": "doing"})
    assert resp.status_code == 302
    own.refresh_from_db()
    assert own.status == "doing"
    resp = client.post(reverse("tasks:step_status", args=[other.pk]), {"status": "done"})
    assert resp.status_code == 403
    other.refresh_from_db()
    assert other.status == "todo"


def test_stranger_cannot_change_step(client, project, bob):
    step = project.steps.first()
    login(client, bob)
    assert client.post(reverse("tasks:step_status", args=[step.pk]), {"status": "done"}).status_code == 404


# ------------------------------------------------------------- step status toggle

def test_step_status_toggle_sets_completed_at(client, project, alice):
    step = project.steps.order_by("order").first()
    login(client, alice)
    url = reverse("tasks:step_status", args=[step.pk])

    client.post(url)  # todo -> doing (chu kỳ)
    step.refresh_from_db()
    assert step.status == "doing" and step.completed_at is None

    client.post(url)  # doing -> done
    step.refresh_from_db()
    assert step.status == "done" and step.completed_at is not None

    client.post(url, {"status": "todo"})
    step.refresh_from_db()
    assert step.status == "todo" and step.completed_at is None


def test_step_status_htmx_returns_partial(client, project, alice):
    step = project.steps.order_by("order").first()
    login(client, alice)
    resp = client.post(reverse("tasks:step_status", args=[step.pk]), {"status": "done"},
                       HTTP_HX_REQUEST="true")
    assert resp.status_code == 200
    html = resp.content.decode()
    assert 'id="steps-section"' in html
    assert "<html" not in html
    assert "17%" in html  # 1/6 bước


def test_step_add_edit_delete(client, project, alice):
    login(client, alice)
    client.post(reverse("tasks:step_add", args=[project.pk]), {"name": "Bước thêm"})
    step = project.steps.get(name="Bước thêm")
    assert step.order == 7
    resp = client.post(reverse("tasks:step_edit", args=[step.pk]),
                       {"name": "Bước sửa", "status": "done", "order": 7, "note": ""})
    assert resp.status_code == 302
    step.refresh_from_db()
    assert step.name == "Bước sửa" and step.completed_at is not None
    client.post(reverse("tasks:step_delete", args=[step.pk]))
    assert not project.steps.filter(pk=step.pk).exists()


def test_list_filters(client, boss, alice, bob):
    Project.objects.create(title="Hội thảo A", kind="workshop", owner=alice)
    Project.objects.create(title="Bài báo B", kind="working_paper", owner=bob)
    login(client, boss)
    html = client.get(reverse("tasks:list"), {"kind": "workshop"}).content.decode()
    assert "Hội thảo A" in html and "Bài báo B" not in html
    html = client.get(reverse("tasks:list"), {"owner": bob.pk}).content.decode()
    assert "Bài báo B" in html and "Hội thảo A" not in html
    html = client.get(reverse("tasks:list"), {"q": "bài"}).content.decode()
    assert "Bài báo B" in html and "Hội thảo A" not in html
