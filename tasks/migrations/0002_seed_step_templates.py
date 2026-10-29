from django.db import migrations

DEFAULTS = {
    "workshop": [
        "Chốt chủ đề & thời gian",
        "Lập tờ trình & dự toán",
        "Mời diễn giả / khách mời",
        "Truyền thông & đăng ký",
        "Tổ chức workshop",
        "Báo cáo tổng kết & quyết toán",
    ],
    "working_paper": [
        "Bản thảo",
        "Góp ý nội bộ",
        "Phản biện",
        "Chỉnh sửa theo phản biện",
        "Biên tập & dàn trang",
        "Công bố trong series",
    ],
}


def seed(apps, schema_editor):
    StepTemplate = apps.get_model("tasks", "StepTemplate")
    for kind, names in DEFAULTS.items():
        if StepTemplate.objects.filter(kind=kind).exists():
            continue
        StepTemplate.objects.bulk_create(
            [StepTemplate(kind=kind, order=i, name=name) for i, name in enumerate(names, start=1)]
        )


def unseed(apps, schema_editor):
    StepTemplate = apps.get_model("tasks", "StepTemplate")
    for kind, names in DEFAULTS.items():
        StepTemplate.objects.filter(kind=kind, name__in=names).delete()


class Migration(migrations.Migration):
    dependencies = [("tasks", "0001_initial")]

    operations = [migrations.RunPython(seed, unseed)]
