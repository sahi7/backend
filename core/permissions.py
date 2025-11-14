# apps/users/permissions.py
from rest_framework.permissions import BasePermission
from .models import User

class IsPrincipal(BasePermission):
    def has_permission(self, request, view):
        return request.user.role == 'principal'
    
class CanViewTeacherScope(BasePermission):
    """
    Allows:
    - Principal: view any teacher's scope
    - Teacher: view ONLY their own scope
    """
    def has_permission(self, request, view):
        teacher_id = view.kwargs.get('teacher_id')
        if not teacher_id:
            return False

        # Principal can view all
        if request.user.role == 'principal':
            return True

        # Teacher can only view self
        if request.user.role == 'teacher':
            return str(request.user.id) == teacher_id

        return False