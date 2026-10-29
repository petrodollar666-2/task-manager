import mimetypes

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods

from .extract import extract_text
from .forms import DocumentForm, SearchForm
from .models import Document
from .search import attach_snippets, search_documents

PAGE_SIZE = 20


def _visible(user):
    return Document.objects.visible_to(user).select_related("owner", "project", "proposal")


def _get_visible(request, pk):
    return get_object_or_404(_visible(request.user), pk=pk)


def _get_editable(request, pk):
    doc = _get_visible(request, pk)
    if not doc.can_edit(request.user):
        raise PermissionDenied("Bạn không có quyền sửa tài liệu này.")
    return doc


def _apply_upload(doc, uploaded):
    doc.original_filename = uploaded.name[:255]
    doc.mime_type = (
        getattr(uploaded, "content_type", "")
        or mimetypes.guess_type(uploaded.name)[0]
        or ""
    )[:150]
    doc.extracted_text = extract_text(uploaded, uploaded.name, doc.mime_type)


@login_required
def search(request):
    form = SearchForm(request.GET or None, user=request.user)
    qs = _visible(request.user)
    q = ""
    if form.is_valid():
        q = form.cleaned_data["q"].strip()
        if form.cleaned_data["source"]:
            qs = qs.filter(source=form.cleaned_data["source"])
        if form.cleaned_data["project"]:
            qs = qs.filter(project=form.cleaned_data["project"])
    results, terms = search_documents(qs, q)
    paginator = Paginator(results, PAGE_SIZE)
    page = paginator.get_page(request.GET.get("page"))
    documents = attach_snippets(page.object_list, terms)

    params = request.GET.copy()
    params.pop("page", None)
    return render(request, "files/search.html", {
        "form": form,
        "q": q,
        "page": page,
        "documents": documents,
        "count": paginator.count,
        "querystring": params.urlencode(),
    })


@login_required
def upload(request):
    form = DocumentForm(request.POST or None, request.FILES or None, user=request.user)
    if request.method == "POST" and form.is_valid():
        doc = form.save(commit=False)
        doc.owner = request.user
        doc.source = Document.Source.UPLOAD
        _apply_upload(doc, form.cleaned_data["file"])
        doc.save()  # save() cập nhật luôn search_vector
        if doc.extracted_text:
            messages.success(request, f"Đã tải lên “{doc.name}” và trích xuất nội dung để tìm kiếm.")
        else:
            messages.success(request, f"Đã tải lên “{doc.name}” (không trích xuất được nội dung, chỉ tìm theo tên/mô tả).")
        return redirect("files:detail", pk=doc.pk)
    return render(request, "files/form.html", {"form": form, "is_edit": False})


@login_required
def detail(request, pk):
    doc = _get_visible(request, pk)
    return render(request, "files/detail.html", {
        "doc": doc,
        "can_edit": doc.can_edit(request.user),
        "preview": doc.extracted_text[:5000],
        "preview_truncated": len(doc.extracted_text) > 5000,
    })


@login_required
def edit(request, pk):
    doc = _get_editable(request, pk)
    old_file = doc.file.name if doc.file else ""
    form = DocumentForm(request.POST or None, request.FILES or None, instance=doc, user=request.user)
    if request.method == "POST" and form.is_valid():
        doc = form.save(commit=False)
        new_file = request.FILES.get("file")
        if new_file:
            _apply_upload(doc, new_file)
        doc.save()
        if new_file and old_file and old_file != doc.file.name:
            doc.file.storage.delete(old_file)
        messages.success(request, "Đã cập nhật tài liệu.")
        return redirect("files:detail", pk=doc.pk)
    return render(request, "files/form.html", {"form": form, "is_edit": True, "doc": doc})


@login_required
@require_http_methods(["GET", "POST"])
def delete(request, pk):
    doc = _get_editable(request, pk)
    if request.method == "POST":
        name = doc.name
        if doc.file:
            doc.file.delete(save=False)
        doc.delete()
        messages.success(request, f"Đã xoá tài liệu “{name}”.")
        return redirect("files:search")
    return render(request, "files/confirm_delete.html", {"doc": doc})


@login_required
def download(request, pk):
    doc = _get_visible(request, pk)
    if not doc.file:
        if doc.drive_url:
            return redirect(doc.drive_url)
        raise Http404("Tài liệu không có file đính kèm.")
    try:
        fh = doc.file.open("rb")
    except (FileNotFoundError, OSError):
        raise Http404("Không tìm thấy file trên máy chủ.")
    return FileResponse(fh, as_attachment=True, filename=doc.download_filename,
                        content_type=doc.mime_type or None)
