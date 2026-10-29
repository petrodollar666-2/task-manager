from django.urls import path

from . import views

app_name = "approvals"

urlpatterns = [
    path("", views.proposal_list, name="list"),
    path("moi/", views.proposal_create, name="create"),
    path("<int:pk>/", views.proposal_detail, name="detail"),
    path("<int:pk>/sua/", views.proposal_edit, name="edit"),
    path("<int:pk>/xoa/", views.proposal_delete, name="delete"),
    path("<int:pk>/nop/", views.proposal_submit, name="submit"),
    path("<int:pk>/file/", views.attachment_download, name="attachment"),
    path("<int:pk>/file/tai-len/", views.attachment_upload, name="attachment_upload"),
    path("<int:pk>/them-chang/", views.stage_add, name="stage_add"),
    path("chang/<int:pk>/ky/", views.stage_sign, name="stage_sign"),
    path("chang/<int:pk>/tra-lai/", views.stage_reject, name="stage_reject"),
    path("chang/<int:pk>/hoan-tac/", views.stage_reset, name="stage_reset"),
    path("chang/<int:pk>/sua/", views.stage_edit, name="stage_edit"),
    path("chang/<int:pk>/xoa/", views.stage_delete, name="stage_delete"),
    path("chang/<int:pk>/chuyen/<str:direction>/", views.stage_move, name="stage_move"),
]
