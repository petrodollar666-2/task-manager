from django.urls import path

from . import views

app_name = "availability"

urlpatterns = [
    path("", views.schedule, name="schedule"),
    path("trang-thai/", views.status_table, name="status_table"),
    path("buoi-day/them/", views.slot_create, name="slot_create"),
    path("buoi-day/<int:pk>/sua/", views.slot_edit, name="slot_edit"),
    path("buoi-day/<int:pk>/xoa/", views.slot_delete, name="slot_delete"),
    path("vang-mat/them/", views.absence_create, name="absence_create"),
    path("vang-mat/<int:pk>/sua/", views.absence_edit, name="absence_edit"),
    path("vang-mat/<int:pk>/xoa/", views.absence_delete, name="absence_delete"),
]
