from django.core.management.base import BaseCommand

from files.models import Document


class Command(BaseCommand):
    help = "Trích xuất lại nội dung các tài liệu đã tải lên và dựng lại chỉ mục tìm kiếm."

    def add_arguments(self, parser):
        parser.add_argument(
            "--vectors-only", dest="vectors_only", action="store_true",
            help="Chỉ dựng lại search_vector, không trích xuất lại nội dung file.",
        )
        parser.add_argument("--id", dest="ids", type=int, nargs="*", help="Chỉ xử lý các tài liệu có id này.")

    def handle(self, *args, vectors_only=False, ids=None, **options):
        qs = Document.objects.all()
        if ids:
            qs = qs.filter(pk__in=ids)
        extracted = failed = 0
        if not vectors_only:
            for doc in qs.exclude(file="").iterator(chunk_size=50):
                chars = doc.reextract(save=False)
                Document.objects.filter(pk=doc.pk).update(extracted_text=doc.extracted_text)
                if chars:
                    extracted += 1
                else:
                    failed += 1
                    self.stdout.write(f"  ! Không trích xuất được nội dung: #{doc.pk} {doc.name}")
        updated = qs.update_search_vectors()
        self.stdout.write(self.style.SUCCESS(
            f"Xong: trích xuất {extracted} tài liệu, {failed} không có nội dung; "
            f"cập nhật chỉ mục cho {updated} tài liệu."
        ))
