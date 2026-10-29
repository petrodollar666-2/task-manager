from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import include, path

from availability.views import dashboard

admin.site.site_header = "Quản trị hệ thống công việc Khoa"
admin.site.site_title = "Quản trị"

urlpatterns = [
    path("", dashboard, name="dashboard"),
    path("dang-nhap/", auth_views.LoginView.as_view(), name="login"),
    path("dang-xuat/", auth_views.LogoutView.as_view(), name="logout"),
    path("viec/", include("tasks.urls")),
    path("to-trinh/", include("approvals.urls")),
    path("lich/", include("availability.urls")),
    path("tai-lieu/", include("files.urls")),
    path("quan-tri/", admin.site.urls),
]
# File tải lên KHÔNG được phục vụ công khai qua MEDIA_URL: mọi lượt tải đi qua
# view có kiểm tra quyền (files:download, approvals:attachment).
