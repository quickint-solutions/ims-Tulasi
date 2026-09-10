from django.urls import path

from . import views

app_name = "accounts"

urlpatterns = [
    path("login/", views.AppLoginView.as_view(), name="login"),
    path("logout/", views.AppLogoutView.as_view(), name="logout"),
    path("profile/", views.profile, name="profile"),
    path("users/", views.UserListView.as_view(), name="user_list"),
    path("users/new/", views.UserCreateView.as_view(), name="user_create"),
    path("users/<int:pk>/", views.UserUpdateView.as_view(), name="user_update"),
    path("roles/", views.RoleListView.as_view(), name="role_list"),
    path("roles/new/", views.RoleCreateView.as_view(), name="role_create"),
    path("roles/<int:pk>/", views.RoleUpdateView.as_view(), name="role_update"),
    path("activity/", views.AuditLogView.as_view(), name="audit_log"),
]
