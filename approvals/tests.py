import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from approvals.models import ApprovalRouteTemplate, ApprovalStage, Proposal
from approvals.services import create_stages_from_templates
from tasks.models import Project

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def media_tmp(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path


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
def proposal(alice):
    p = Proposal.objects.create(title="Tờ trình workshop", kind=Proposal.Kind.PROPOSAL, owner=alice)
    create_stages_from_templates(p)
    return p


def stages(p):
    return list(p.stages.order_by("order"))


# ------------------------------------------------------------- seed & generation

def test_seeded_route_templates():
    prop = list(ApprovalRouteTemplate.objects.filter(kind="proposal").order_by("order")
                .values_list("department", "signer_name"))
    fin = list(ApprovalRouteTemplate.objects.filter(kind="finance").order_by("order")
               .values_list("department", "signer_name"))
    assert prop == [
        ("Bộ môn / Khoa", "Trưởng khoa"),
        ("Phòng Quản lý Khoa học", "Trưởng phòng QLKH"),
        ("Phòng Kế hoạch – Tài chính", "Trưởng phòng KH-TC"),
        ("Ban Giám hiệu", "Phó Hiệu trưởng phụ trách"),
    ]
    assert len(fin) == 5
    assert fin[3] == ("Phòng Kế hoạch – Tài chính", "Kế toán trưởng")
    assert fin[4] == ("Ban Giám hiệu", "Phó Hiệu trưởng phụ trách")


def test_create_view_generates_stages(client, alice):
    client.force_login(alice)
    resp = client.post(reverse("approvals:create"), {
        "title": "Kế hoạch tài chính 2026", "kind": "finance", "amount": "50000000",
        "attachment": SimpleUploadedFile("dutoan.pdf", b"%PDF-1.4 test"),
    })
    assert resp.status_code == 302
    p = Proposal.objects.get(title="Kế hoạch tài chính 2026")
    assert p.owner == alice
    assert p.status == Proposal.Status.DRAFT
    assert p.total_count == 5
    assert p.attachment.name.endswith(".pdf")


def test_create_form_limits_projects(client, alice, bob):
    own = Project.objects.create(title="Của Alice", owner=alice)
    other = Project.objects.create(title="Của Bob", owner=bob)
    client.force_login(alice)
    html = client.get(reverse("approvals:create")).content.decode()
    assert own.title in html and other.title not in html
    resp = client.post(reverse("approvals:create"), {"title": "X", "kind": "proposal", "project": other.pk})
    assert resp.status_code == 200  # lỗi form: đầu việc không hợp lệ
    assert not Proposal.objects.filter(title="X").exists()


# ------------------------------------------------------------- counting

def test_signature_counting(proposal):
    s = stages(proposal)
    assert (proposal.signed_count, proposal.total_count, proposal.remaining_count) == (0, 4, 4)
    assert proposal.current_stage == s[0]
    assert proposal.current_stage.department == "Bộ môn / Khoa"

    for st in s[:2]:
        st.status = ApprovalStage.Status.SIGNED
        st.save()
    assert (proposal.signed_count, proposal.remaining_count) == (2, 2)
    assert proposal.current_stage.department == "Phòng Kế hoạch – Tài chính"
    assert [m.department for m in proposal.missing_signers] == ["Phòng Kế hoạch – Tài chính", "Ban Giám hiệu"]


# ------------------------------------------------------------- refresh_status

def test_refresh_status_transitions(proposal):
    s = stages(proposal)
    assert proposal.refresh_status() == Proposal.Status.DRAFT

    proposal.submitted_at = timezone.localdate()
    assert proposal.refresh_status() == Proposal.Status.IN_PROGRESS

    s[0].status = ApprovalStage.Status.REJECTED
    s[0].save()
    assert proposal.refresh_status() == Proposal.Status.REJECTED

    proposal.stages.update(status=ApprovalStage.Status.SIGNED)
    assert proposal.refresh_status() == Proposal.Status.APPROVED
    proposal.refresh_from_db()
    assert proposal.status == Proposal.Status.APPROVED


def test_refresh_status_signed_without_submission(alice):
    p = Proposal.objects.create(title="T", owner=alice)
    ApprovalStage.objects.create(proposal=p, order=1, department="A", status="signed")
    ApprovalStage.objects.create(proposal=p, order=2, department="B")
    assert p.refresh_status() == Proposal.Status.IN_PROGRESS


# ------------------------------------------------------------- actions

def test_submit_sets_submitted_at(client, proposal, alice):
    client.force_login(alice)
    client.post(reverse("approvals:submit", args=[proposal.pk]))
    proposal.refresh_from_db()
    assert proposal.submitted_at == timezone.localdate()
    assert proposal.status == Proposal.Status.IN_PROGRESS


def test_sign_action(client, proposal, alice):
    client.force_login(alice)
    s = stages(proposal)
    resp = client.post(reverse("approvals:stage_sign", args=[s[0].pk]), HTTP_HX_REQUEST="true")
    assert resp.status_code == 200
    html = resp.content.decode()
    assert 'id="proposal-panel"' in html and "1/4" in html
    s[0].refresh_from_db()
    assert s[0].status == "signed" and s[0].signed_at is not None
    proposal.refresh_from_db()
    assert proposal.status == Proposal.Status.IN_PROGRESS
    assert proposal.current_stage == s[1]

    # không được ký vượt chặng
    assert client.post(reverse("approvals:stage_sign", args=[s[3].pk])).status_code == 403

    for st in s[1:]:
        assert client.post(reverse("approvals:stage_sign", args=[st.pk])).status_code == 302
    proposal.refresh_from_db()
    assert proposal.status == Proposal.Status.APPROVED
    assert proposal.remaining_count == 0


def test_reject_and_resubmit(client, proposal, boss):
    client.force_login(boss)
    s = stages(proposal)
    client.post(reverse("approvals:submit", args=[proposal.pk]))
    client.post(reverse("approvals:stage_sign", args=[s[0].pk]))
    client.post(reverse("approvals:stage_reject", args=[s[1].pk]), {"note": "Thiếu dự toán"})
    s[1].refresh_from_db()
    assert s[1].status == "rejected" and s[1].note == "Thiếu dự toán"
    proposal.refresh_from_db()
    assert proposal.status == Proposal.Status.REJECTED

    client.post(reverse("approvals:submit", args=[proposal.pk]))
    s[1].refresh_from_db()
    proposal.refresh_from_db()
    assert s[1].status == "pending"
    assert proposal.status == Proposal.Status.IN_PROGRESS


def test_stage_add_move_delete(client, proposal, alice):
    client.force_login(alice)
    client.post(reverse("approvals:stage_add", args=[proposal.pk]),
                {"department": "Phòng Hợp tác Quốc tế", "signer_name": "Trưởng phòng"})
    s = stages(proposal)
    assert s[-1].department == "Phòng Hợp tác Quốc tế" and s[-1].order == 5
    client.post(reverse("approvals:stage_move", args=[s[-1].pk, "up"]))
    assert [x.department for x in stages(proposal)][3] == "Phòng Hợp tác Quốc tế"
    client.post(reverse("approvals:stage_delete", args=[s[-1].pk]))
    assert proposal.total_count == 4


def test_no_stage_changes_after_approved(client, proposal, alice):
    proposal.stages.update(status=ApprovalStage.Status.SIGNED)
    proposal.refresh_status()
    client.force_login(alice)
    resp = client.post(reverse("approvals:stage_add", args=[proposal.pk]), {"department": "X"})
    assert resp.status_code == 403


# ------------------------------------------------------------- permissions

def test_member_cannot_view_other_members_proposal(client, proposal, bob):
    client.force_login(bob)
    assert client.get(reverse("approvals:detail", args=[proposal.pk])).status_code == 404
    assert client.get(reverse("approvals:attachment", args=[proposal.pk])).status_code == 404
    s = stages(proposal)
    assert client.post(reverse("approvals:stage_sign", args=[s[0].pk])).status_code == 404
    assert proposal.title not in client.get(reverse("approvals:list")).content.decode()


def test_boss_and_owner_can_view(client, proposal, alice, boss):
    for user in (alice, boss):
        client.force_login(user)
        resp = client.get(reverse("approvals:detail", args=[proposal.pk]))
        assert resp.status_code == 200
        assert "Đánh dấu đã ký" in resp.content.decode()
        assert proposal.title in client.get(reverse("approvals:list")).content.decode()


def test_attachment_download_protected(client, proposal, alice):
    proposal.attachment = SimpleUploadedFile("totrinh.pdf", b"noi dung")
    proposal.save()
    client.force_login(alice)
    resp = client.get(reverse("approvals:attachment", args=[proposal.pk]))
    assert resp.status_code == 200
    assert b"".join(resp.streaming_content) == b"noi dung"
    assert "attachment" in resp["Content-Disposition"]


def test_list_shows_progress_info(client, proposal, alice):
    s = stages(proposal)
    s[0].status = ApprovalStage.Status.SIGNED
    s[0].save()
    client.force_login(alice)
    html = client.get(reverse("approvals:list")).content.decode()
    assert "Đã ký 1/4" in html
    assert "Phòng Quản lý Khoa học" in html
    html = client.get(reverse("approvals:list"), {"status": "approved"}).content.decode()
    assert proposal.title not in html
