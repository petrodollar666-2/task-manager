"""Thẻ giao diện dùng chung: badge trạng thái, thanh tiến độ, định dạng tiền."""

from decimal import Decimal, InvalidOperation

from django import template
from django.utils.html import format_html

register = template.Library()

GREEN = "bg-green-100 text-green-800 ring-green-200"
AMBER = "bg-amber-100 text-amber-800 ring-amber-200"
SLATE = "bg-slate-100 text-slate-700 ring-slate-200"
RED = "bg-red-100 text-red-800 ring-red-200"
INDIGO = "bg-indigo-100 text-indigo-800 ring-indigo-200"
SKY = "bg-sky-100 text-sky-800 ring-sky-200"
VIOLET = "bg-violet-100 text-violet-800 ring-violet-200"
EMERALD = "bg-emerald-100 text-emerald-800 ring-emerald-200"

BADGE_COLORS = {
    # trạng thái
    "done": GREEN,
    "signed": GREEN,
    "approved": GREEN,
    "doing": AMBER,
    "in_progress": AMBER,
    "active": AMBER,
    "todo": SLATE,
    "pending": SLATE,
    "draft": SLATE,
    "paused": SLATE,
    "rejected": RED,
    "overdue": RED,
    # loại
    "workshop": INDIGO,
    "working_paper": SKY,
    "proposal": VIOLET,
    "finance": EMERALD,
    "other": SLATE,
}


@register.simple_tag
def badge(key, label):
    cls = BADGE_COLORS.get(key, SLATE)
    return format_html(
        '<span class="inline-flex items-center whitespace-nowrap rounded-full px-2 py-0.5 '
        'text-xs font-medium ring-1 ring-inset {}">{}</span>',
        cls,
        label,
    )


@register.simple_tag
def progress_bar(pct, size="h-2"):
    try:
        pct = max(0, min(100, int(pct)))
    except (TypeError, ValueError):
        pct = 0
    color = "bg-green-500" if pct >= 100 else "bg-indigo-500"
    return format_html(
        '<div class="w-full overflow-hidden rounded-full bg-slate-200 {}" role="progressbar" '
        'aria-valuenow="{}" aria-valuemin="0" aria-valuemax="100">'
        '<div class="{} {}" style="width: {}%"></div></div>',
        size, pct, size, color, pct,
    )


@register.filter
def percent(part, total):
    try:
        total = int(total)
        return round(int(part) * 100 / total) if total else 0
    except (TypeError, ValueError):
        return 0


@register.filter
def vnd(value):
    """1234567 -> '1.234.567 đ'."""
    if value in (None, ""):
        return ""
    try:
        n = int(Decimal(value))
    except (InvalidOperation, TypeError, ValueError):
        return value
    return f"{n:,}".replace(",", ".") + " đ"
