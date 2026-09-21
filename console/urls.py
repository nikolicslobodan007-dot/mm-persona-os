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
    path("content", views.content, name="console-content"),
    path("actions/<str:action_id>", views.action, name="console-action"),
    path("costs", views.costs, name="console-costs"),
    path("incidents", views.incidents, name="console-incidents"),
    path("kill-switch", views.kill_switch, name="console-kill-switch"),
]
