from django.urls import path

from . import views

app_name = "tasks"

urlpatterns = [
    path("", views.project_list, name="list"),
    path("moi/", views.project_create, name="create"),
    path("<int:pk>/", views.project_detail, name="detail"),
    path("<int:pk>/sua/", views.project_edit, name="edit"),
    path("<int:pk>/xoa/", views.project_delete, name="delete"),
    path("<int:pk>/them-buoc/", views.step_add, name="step_add"),
    path("buoc/<int:pk>/sua/", views.step_edit, name="step_edit"),
    path("buoc/<int:pk>/xoa/", views.step_delete, name="step_delete"),
    path("buoc/<int:pk>/trang-thai/", views.step_status, name="step_status"),
]
