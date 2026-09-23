from django.urls import path

from console import views

urlpatterns = [
    path("", views.overview, name="console-overview"),
    path("login", views.login_view, name="console-login"),
    path("login/2fa", views.totp_view, name="console-totp"),
    path("logout", views.logout_view, name="console-logout"),
    path("approvals", views.approvals, name="console-approvals"),
    path("approvals/<str:approval_id>/decide", views.approval_decide,
         name="console-approval-decide"),
    path("personas/<str:public_id>", views.persona, name="console-persona"),
    path("personas/<str:public_id>/status", views.persona_status,
         name="console-persona-status"),
    path("personas/<str:public_id>/draft", views.persona_draft,
         name="console-persona-draft"),
    path("personas/<str:public_id>/lessons", views.persona_lesson_add,
         name="console-persona-lesson-add"),
    path("org", views.org_chart, name="console-org"),
    path("personas/<str:public_id>/assign", views.persona_assign,
         name="console-persona-assign"),
    path("personas/<str:public_id>/dossier", views.persona_dossier,
         name="console-persona-dossier"),
    path("personas/<str:public_id>/mailbox", views.persona_mailbox,
         name="console-persona-mailbox"),
    path("lessons/<uuid:lesson_id>/toggle", views.lesson_toggle, name="console-lesson-toggle"),
    path("content", views.content, name="console-content"),
    path("actions/<str:action_id>", views.action, name="console-action"),
    path("costs", views.costs, name="console-costs"),
    path("incidents", views.incidents, name="console-incidents"),
    path("kill-switch", views.kill_switch, name="console-kill-switch"),
]
