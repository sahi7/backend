# apps/users/permissions.py
from rest_framework.permissions import BasePermission
from .models import User

class IsPrincipal(BasePermission):
    def has_permission(self, request, view):
        return request.user.role == 'principal'