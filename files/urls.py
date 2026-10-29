from django.urls import path

from . import views

app_name = "files"

urlpatterns = [
    path("", views.search, name="search"),
    path("tai-len/", views.upload, name="upload"),
    path("<int:pk>/", views.detail, name="detail"),
    path("<int:pk>/sua/", views.edit, name="edit"),
    path("<int:pk>/xoa/", views.delete, name="delete"),
    path("<int:pk>/tai-ve/", views.download, name="download"),
]
