"""Tìm kiếm tài liệu theo từ khoá (không dùng AI).

- Full-text search của Postgres trên search_vector (tên A, mô tả B, nội dung C),
  cấu hình "simple" + unaccent nên gõ không dấu vẫn tìm được có dấu và ngược lại
  ("dao tao" ↔ "Đào tạo").
- Mỗi từ được khớp tiền tố (`'tu':*`) nên gõ dở chữ vẫn ra kết quả.
- Nếu không có kết quả: fallback sang độ tương tự trigram trên tên đã bỏ dấu.
- Đoạn trích (snippet) được cắt quanh vị trí khớp đầu tiên và tô sáng bằng
  <mark> trên văn bản gốc (có dấu); mọi nội dung khác đều được escape HTML.
"""

import re
import unicodedata

from django.contrib.postgres.search import (
    SearchQuery,
    SearchRank,
    TrigramSimilarity,
    TrigramWordSimilarity,
)
from django.db import connection
from django.db.models import F, Func, IntegerField, Q, Value
from django.db.models.functions import Coalesce, Greatest, Least, NullIf, Substr
from django.utils.html import escape
from django.utils.safestring import mark_safe

from .models import Document, unaccent

MAX_TERMS = 10
SNIPPET_BEFORE = 100
SNIPPET_LEN = 320
TRIGRAM_SIMILARITY = 0.2
TRIGRAM_WORD_SIMILARITY = 0.5

_SPLIT_RE = re.compile(r"[\W_]+", re.UNICODE)
_OPERATOR_RE = re.compile(r'"|(^|\s)-\w|(^|\s)or(\s|$)', re.IGNORECASE)


# --------------------------------------------------------------------------
# Chuẩn hoá truy vấn
# --------------------------------------------------------------------------
def db_unaccent(text):
    """Bỏ dấu bằng chính hàm unaccent của Postgres (đồng nhất với chỉ mục)."""
    with connection.cursor() as cursor:
        cursor.execute("SELECT unaccent(%s)", [text])
        return cursor.fetchone()[0]


def query_terms(normalized):
    terms = [t for t in _SPLIT_RE.split(normalized.lower()) if t]
    # Bỏ trùng nhưng giữ thứ tự.
    return list(dict.fromkeys(terms))[:MAX_TERMS]


def prefix_tsquery(terms):
    """Tạo tsquery dạng raw: 'ke':* & 'hoach':* (đã escape an toàn)."""
    parts = []
    for term in terms:
        safe = term.replace("\\", "\\\\").replace("'", "''")
        parts.append(f"'{safe}':*")
    return " & ".join(parts)


def build_query(q):
    """Trả về (SearchQuery, normalized_text, terms) hoặc (None, "", [])."""
    normalized = db_unaccent(q).lower().strip()
    terms = query_terms(normalized)
    if not terms:
        return None, normalized, []
    query = SearchQuery(normalized, search_type="websearch", config="simple")
    if not _OPERATOR_RE.search(q):
        # Truy vấn thường: thêm khớp tiền tố cho từng từ.
        query = query | SearchQuery(prefix_tsquery(terms), search_type="raw", config="simple")
    return query, normalized, terms


def search_documents(queryset, q):
    """Lọc + xếp hạng queryset theo q. Trả về (queryset, terms)."""
    q = (q or "").strip()
    if not q:
        return queryset.order_by("-created_at"), []
    query, normalized, terms = build_query(q)
    if query is None:
        return queryset.none(), []

    results = (
        queryset.filter(search_vector=query)
        .annotate(rank=SearchRank(F("search_vector"), query))
        .order_by("-rank", "-created_at")
    )
    if results.exists():
        return results, terms

    # Fallback: gõ sai chính tả / thiếu ký tự → so khớp gần đúng trên tên.
    name = unaccent("name")
    fuzzy = (
        queryset.annotate(
            sim=TrigramSimilarity(name, normalized),
            wsim=TrigramWordSimilarity(normalized, name),
        )
        .filter(Q(sim__gt=TRIGRAM_SIMILARITY) | Q(wsim__gt=TRIGRAM_WORD_SIMILARITY))
        .annotate(rank=Greatest("sim", "wsim"))
        .order_by("-rank", "-created_at")
    )
    return fuzzy, terms


# --------------------------------------------------------------------------
# Đoạn trích + tô sáng
# --------------------------------------------------------------------------
def _fold_char(ch):
    if ch in "đĐ":
        return "d"
    base = "".join(c for c in unicodedata.normalize("NFD", ch) if not unicodedata.combining(c))
    low = (base or ch).lower()
    return low[0] if low else ch


def fold(text):
    """Bỏ dấu + chữ thường, GIỮ NGUYÊN độ dài (mỗi ký tự → đúng 1 ký tự) để
    vị trí khớp trên chuỗi đã bỏ dấu ánh xạ thẳng về chuỗi gốc."""
    return "".join(_fold_char(c) for c in text)


def highlight(text, terms):
    """HTML an toàn: escape toàn bộ, chỉ bọc phần khớp bằng <mark>."""
    text = text or ""
    if not terms:
        return mark_safe(escape(text))
    folded = fold(text)
    spans = []
    for term in terms:
        pattern = r"(?<!\w)" + re.escape(term) + r"\w*"
        spans.extend(m.span() for m in re.finditer(pattern, folded))
    if not spans:
        return mark_safe(escape(text))
    spans.sort()
    merged = [list(spans[0])]
    for start, end in spans[1:]:
        if start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    out, pos = [], 0
    for start, end in merged:
        out.append(escape(text[pos:start]))
        out.append('<mark class="rounded bg-yellow-200 px-0.5">' + escape(text[start:end]) + "</mark>")
        pos = end
    out.append(escape(text[pos:]))
    return mark_safe("".join(out))


def _trim(excerpt, start, full_len_reached):
    excerpt = re.sub(r"\s+", " ", excerpt).strip()
    if start > 1 and " " in excerpt:
        excerpt = "… " + excerpt.split(" ", 1)[1]
    if full_len_reached and " " in excerpt:
        excerpt = excerpt.rsplit(" ", 1)[0] + " …"
    return excerpt


def attach_snippets(documents, terms):
    """Gắn doc.snippet_html và doc.name_html cho danh sách tài liệu (1 trang)."""
    documents = list(documents)
    if not documents:
        return documents
    if terms:
        positions = [
            NullIf(
                Func(
                    unaccent("extracted_text"),
                    Value(r"\m" + re.escape(term)),
                    Value(1), Value(1), Value(0), Value("i"),
                    function="regexp_instr",
                    output_field=IntegerField(),
                ),
                Value(0),
            )
            for term in terms[:5]
        ]
        first = positions[0] if len(positions) == 1 else Least(*positions)
        start = Greatest(Coalesce(first, Value(1)) - Value(SNIPPET_BEFORE), Value(1))
    else:
        start = Value(1)
    rows = (
        Document.objects.filter(pk__in=[d.pk for d in documents])
        .annotate(snip_start=start)
        .annotate(snip=Substr("extracted_text", F("snip_start"), SNIPPET_LEN))
        .values_list("pk", "snip_start", "snip")
    )
    snippets = {pk: (s, text or "") for pk, s, text in rows}
    for doc in documents:
        s, text = snippets.get(doc.pk, (1, ""))
        if not text.strip():
            text, s = doc.description[:SNIPPET_LEN], 1
        excerpt = _trim(text, s, len(text) >= SNIPPET_LEN)
        doc.snippet_html = highlight(excerpt, terms)
        doc.name_html = highlight(doc.name, terms)
    return documents
