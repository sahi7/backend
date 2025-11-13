# apps/users/serializers.py
from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from django.contrib.auth import get_user_model

user = get_user_model()

class CustomTokenObtainPairSerializer(TokenObtainPairSerializer):
    @classmethod
    def get_token(cls, user):
        token = super().get_token(user)

        # Add custom claims
        token['role'] = user.role
        token['name'] = user.get_full_name() or user.username
        token['email'] = user.email
        token['department'] = user.department.name if user.department else None

        return token

    def validate(self, attrs):
        data = super().validate(attrs)

        # Add user details to response
        data['user'] = {
            'id': self.user.id,
            'username': self.user.username,
            'email': self.user.email,
            'full_name': self.user.get_full_name(),
            'role': self.user.role,
            'department': self.user.department.name if self.user.department else None,
            'taught_subjects': [
                {'code': s.code, 'name': s.name}
                for s in self.user.taught_subjects.all()
            ] if self.user.role == 'teacher' else []
        }

        return data