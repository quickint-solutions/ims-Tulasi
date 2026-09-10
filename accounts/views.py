from django.contrib import messages
from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import PasswordChangeForm
from django.contrib.auth.views import LoginView, LogoutView
from django.core.paginator import Paginator
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse_lazy
from django.utils import timezone
from django.views.generic import CreateView, ListView, UpdateView

from core.mixins import (AppPermissionRequiredMixin, PageContextMixin,
                         app_permission_required, querystring_without_page)
from . import audit
from .forms import LoginForm, ProfileForm, RoleForm, UserForm
from .models import AuditLog, Role, User


class AppLoginView(LoginView):
    template_name = "accounts/login.html"
    authentication_form = LoginForm
    redirect_authenticated_user = True

    def form_valid(self, form):
        response = super().form_valid(form)
        User.objects.filter(pk=self.request.user.pk).update(last_activity=timezone.now())
        audit.log(AuditLog.Action.LOGIN, user=self.request.user,
                  description="Signed in")
        return response

    def form_invalid(self, form):
        audit.log(AuditLog.Action.LOGIN_FAILED,
                  object_label=form.data.get("username", "")[:255],
                  description="Failed sign-in attempt")
        return super().form_invalid(form)


class AppLogoutView(LogoutView):
    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated:
            audit.log(AuditLog.Action.LOGOUT, user=request.user, description="Signed out")
        return super().dispatch(request, *args, **kwargs)


class UserListView(AppPermissionRequiredMixin, PageContextMixin, ListView):
    required_permission = "user.view"
    template_name = "accounts/user_list.html"
    context_object_name = "users"
    paginate_by = 50
    page_title = "Users"
    page_subtitle = "Accounts, roles and warehouse access."
    nav = "users"

    def get_queryset(self):
        qs = User.objects.select_related("role").order_by("username")
        q = self.request.GET.get("q", "").strip()
        if q:
            qs = qs.filter(Q(username__icontains=q) | Q(first_name__icontains=q)
                           | Q(last_name__icontains=q) | Q(email__icontains=q)
                           | Q(employee_code__icontains=q))
        role = self.request.GET.get("role")
        if role:
            qs = qs.filter(role_id=role)
        status = self.request.GET.get("status")
        if status == "active":
            qs = qs.filter(is_active=True)
        elif status == "inactive":
            qs = qs.filter(is_active=False)
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["roles"] = Role.objects.all()
        return ctx


class UserCreateView(AppPermissionRequiredMixin, PageContextMixin, CreateView):
    required_permission = "user.manage"
    model = User
    form_class = UserForm
    template_name = "accounts/user_form.html"
    success_url = reverse_lazy("accounts:user_list")
    page_title = "New user"
    nav = "users"

    def form_valid(self, form):
        response = super().form_valid(form)
        audit.log(AuditLog.Action.USER_CHANGE, obj=self.object,
                  description=f"Created user {self.object.username}")
        messages.success(self.request, f"User {self.object.username} created.")
        return response


class UserUpdateView(AppPermissionRequiredMixin, PageContextMixin, UpdateView):
    required_permission = "user.manage"
    model = User
    form_class = UserForm
    template_name = "accounts/user_form.html"
    success_url = reverse_lazy("accounts:user_list")
    nav = "users"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["page_title"] = f"Edit user: {self.object.username}"
        return ctx

    def form_valid(self, form):
        response = super().form_valid(form)
        audit.log(AuditLog.Action.USER_CHANGE, obj=self.object,
                  description=f"Updated user {self.object.username}",
                  changes={k: str(form.cleaned_data.get(k)) for k in form.changed_data
                           if "password" not in k})
        messages.success(self.request, f"User {self.object.username} updated.")
        return response


class RoleListView(AppPermissionRequiredMixin, PageContextMixin, ListView):
    required_permission = "user.view"
    model = Role
    template_name = "accounts/role_list.html"
    context_object_name = "roles"
    page_title = "Roles & permissions"
    page_subtitle = "Every permission is configurable per role."
    nav = "roles"

    def get_queryset(self):
        return Role.objects.prefetch_related("permissions").order_by("name")


class RoleCreateView(AppPermissionRequiredMixin, PageContextMixin, CreateView):
    required_permission = "user.manage"
    model = Role
    form_class = RoleForm
    template_name = "accounts/role_form.html"
    success_url = reverse_lazy("accounts:role_list")
    page_title = "New role"
    nav = "roles"


class RoleUpdateView(AppPermissionRequiredMixin, PageContextMixin, UpdateView):
    required_permission = "user.manage"
    model = Role
    form_class = RoleForm
    template_name = "accounts/role_form.html"
    success_url = reverse_lazy("accounts:role_list")
    nav = "roles"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["page_title"] = f"Role: {self.object.name}"
        return ctx

    def form_valid(self, form):
        response = super().form_valid(form)
        audit.log(AuditLog.Action.USER_CHANGE, obj=self.object,
                  description=f"Updated role {self.object.name}")
        messages.success(self.request, f"Role {self.object.name} updated.")
        return response


class AuditLogView(AppPermissionRequiredMixin, PageContextMixin, ListView):
    required_permission = "audit.view"
    template_name = "accounts/audit_log.html"
    context_object_name = "logs"
    paginate_by = 100
    page_title = "Activity log"
    page_subtitle = "Every login, master change and stock movement is recorded."
    nav = "audit"

    def get_queryset(self):
        qs = AuditLog.objects.select_related("user")
        g = self.request.GET
        if g.get("user"):
            qs = qs.filter(user_id=g["user"])
        if g.get("action"):
            qs = qs.filter(action=g["action"])
        if g.get("document"):
            qs = qs.filter(document_number__icontains=g["document"])
        if g.get("q"):
            qs = qs.filter(Q(object_label__icontains=g["q"])
                           | Q(description__icontains=g["q"]))
        from core.utils import parse_date
        d_from, d_to = parse_date(g.get("date_from")), parse_date(g.get("date_to"))
        if d_from:
            qs = qs.filter(timestamp__date__gte=d_from)
        if d_to:
            qs = qs.filter(timestamp__date__lte=d_to)
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["users"] = User.objects.order_by("username")
        ctx["actions"] = AuditLog.Action.choices
        return ctx


@login_required
def profile(request):
    form = ProfileForm(request.POST or None, instance=request.user)
    pwd_form = PasswordChangeForm(request.user, request.POST or None)
    if request.method == "POST":
        if "save_profile" in request.POST and form.is_valid():
            form.save()
            messages.success(request, "Profile updated.")
            return redirect("accounts:profile")
        if "change_password" in request.POST and pwd_form.is_valid():
            user = pwd_form.save()
            User.objects.filter(pk=user.pk).update(must_change_password=False)
            update_session_auth_hash(request, user)
            audit.log(AuditLog.Action.USER_CHANGE, obj=user, description="Changed own password")
            messages.success(request, "Password changed.")
            return redirect("accounts:profile")
    return render(request, "accounts/profile.html", {
        "form": form, "pwd_form": pwd_form, "page_title": "My profile", "nav": "",
    })
