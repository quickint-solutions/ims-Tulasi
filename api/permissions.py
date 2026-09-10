from rest_framework import permissions

SAFE = permissions.SAFE_METHODS


class HasAppPermission(permissions.BasePermission):
    """Maps HTTP verbs to our application permission codes.

    A request authenticated with an API key must ALSO hold the `write` scope
    before any unsafe verb is allowed - the key's scope and the user's role
    both have to agree.
    """
    read_permission = None
    write_permission = None

    def has_permission(self, request, view):
        user = request.user
        if not (user and user.is_authenticated):
            return False
        api_key = getattr(request, "api_key", None)
        if request.method not in SAFE:
            if api_key is not None and not api_key.can_write:
                return False
            code = getattr(view, "write_permission", None)
            return code is None or user.has_perm_code(code)
        code = getattr(view, "read_permission", None)
        return code is None or user.has_perm_code(code)
