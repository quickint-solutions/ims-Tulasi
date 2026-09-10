from functools import wraps

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect


class AppPermissionRequiredMixin(LoginRequiredMixin):
    """Gate a view on one of our application permission codes."""
    required_permission = None
    required_any = ()

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return super().dispatch(request, *args, **kwargs)
        if not self.has_app_permission(request.user):
            raise PermissionDenied("You do not have permission to open this page.")
        return super().dispatch(request, *args, **kwargs)

    def has_app_permission(self, user):
        if self.required_permission:
            return user.has_perm_code(self.required_permission)
        if self.required_any:
            return any(user.has_perm_code(c) for c in self.required_any)
        return True


def app_permission_required(*codes):
    """Function-view decorator; passes if the user holds ANY of the codes."""
    def outer(view):
        @wraps(view)
        def inner(request, *args, **kwargs):
            if not request.user.is_authenticated:
                return redirect("accounts:login")
            if codes and not any(request.user.has_perm_code(c) for c in codes):
                raise PermissionDenied("You do not have permission to perform this action.")
            return view(request, *args, **kwargs)
        return inner
    return outer


class PageContextMixin:
    """Fills page_title / page_subtitle / nav for the shared shell template."""
    page_title = ""
    page_subtitle = ""
    nav = ""

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx.setdefault("page_title", self.page_title)
        ctx.setdefault("page_subtitle", self.page_subtitle)
        ctx.setdefault("nav", self.nav)
        ctx.setdefault("querystring", querystring_without_page(self.request))
        return ctx


def querystring_without_page(request):
    params = request.GET.copy()
    params.pop("page", None)
    encoded = params.urlencode()
    return encoded + "&" if encoded else ""


class SuccessMessageMixin:
    success_message = ""

    def form_valid(self, form):
        response = super().form_valid(form)
        if self.success_message:
            messages.success(self.request, self.success_message % {"object": self.object})
        return response
