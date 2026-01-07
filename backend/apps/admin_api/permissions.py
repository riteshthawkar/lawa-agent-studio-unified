from rest_framework import permissions

class IsAdminUser(permissions.BasePermission):
    """
    Allows access only to admin users (staff members).
    """
    def has_permission(self, request, view):
        return bool(request.user and request.user.is_staff)
