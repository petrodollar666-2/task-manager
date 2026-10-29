from django.db import migrations

BASE_ROUTE = [
    ("Bộ môn / Khoa", "Trưởng khoa"),
    ("Phòng Quản lý Khoa học", "Trưởng phòng QLKH"),
    ("Phòng Kế hoạch – Tài chính", "Trưởng phòng KH-TC"),
    ("Ban Giám hiệu", "Phó Hiệu trưởng phụ trách"),
]

DEFAULTS = {
    "proposal": BASE_ROUTE,
    "finance": BASE_ROUTE[:3] + [("Phòng Kế hoạch – Tài chính", "Kế toán trưởng")] + BASE_ROUTE[3:],
}


def seed(apps, schema_editor):
    Template = apps.get_model("approvals", "ApprovalRouteTemplate")
    for kind, route in DEFAULTS.items():
        if Template.objects.filter(kind=kind).exists():
            continue
        Template.objects.bulk_create([
            Template(kind=kind, order=i, department=dept, signer_name=signer)
            for i, (dept, signer) in enumerate(route, start=1)
        ])


def unseed(apps, schema_editor):
    Template = apps.get_model("approvals", "ApprovalRouteTemplate")
    for kind, route in DEFAULTS.items():
        for dept, signer in route:
            Template.objects.filter(kind=kind, department=dept, signer_name=signer).delete()


class Migration(migrations.Migration):
    dependencies = [("approvals", "0001_initial")]

    operations = [migrations.RunPython(seed, unseed)]
