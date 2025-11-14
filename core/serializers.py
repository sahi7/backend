# apps/users/serializers.py
import asyncio
from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from django.core.exceptions import ValidationError
from django.contrib.auth import get_user_model

from .models import AcademicYear, Term, ClassRoom, Subject, SubjectAssignment, Mark
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
    
class AcademicYearSerializer(serializers.ModelSerializer):
    class Meta:
        model = AcademicYear
        fields = ['id', 'name', 'start_date', 'end_date', 'is_current', 'created_at']
        read_only_fields = ['created_at']

    def validate(self, data):
        if data['start_date'] >= data['end_date']:
            raise ValidationError("start_date must be before end_date")
        return data

    async def acreate(self, validated_data):
        # Ensure only one current
        if validated_data.get('is_current'):
            await AcademicYear.objects.filter(is_current=True).aupdate(is_current=False)
        return await super().acreate(validated_data)

from asgiref.sync import sync_to_async
class TermSerializer(serializers.ModelSerializer):
    academic_year_name = serializers.CharField(source='academic_year.name', read_only=True)

    class Meta:
        model = Term
        fields = [
            'id', 'academic_year', 'academic_year_name', 'is_current',
            'term_number', 'name', 'start_date', 'end_date'
        ]

    def validate(self, data):
        # 1. Date range
        start_date = data.get('start_date')
        end_date = data.get('end_date')
        if start_date and end_date:
            if start_date >= end_date:
                raise ValidationError("start_date must be before end_date")

        # 2. Term number uniqueness per year (no DB check)
        # → Defer to view
        return data
    
    async def acreate(self, validated_data):
        # Ensure only one current
        if validated_data.get('is_current'):
            await Term.objects.filter(is_current=True).aupdate(is_current=False)
        return await super().acreate(validated_data)


class ClassRoomSerializer(serializers.ModelSerializer):
    class Meta:
        model = ClassRoom
        fields = ['id', 'name']
    
    def validate_name(self, value):
        if not value.strip():
            raise ValidationError("Name cannot be empty")
        return value.strip()
    
class SubjectSerializer(serializers.ModelSerializer):
    class Meta:
        model = Subject
        fields = [
            'id', 'name', 'code', 'coefficient',
            'max_score', 'departments'
        ]

    def validate_code(self, value):
        value = value.upper()
        if Subject.objects.filter(code=value).exclude(pk=self.instance.pk if self.instance else None).exists():
            raise serializers.ValidationError("Subject code must be unique")
        return value
    
class SubjectAssignmentListSerializer(serializers.ModelSerializer):
    subject = serializers.CharField(source='subject.name')
    teacher = serializers.CharField(source='teacher.get_full_name')
    department = serializers.CharField(source='department.name')
    term = serializers.CharField(source='term.name')
    academic_year = serializers.CharField(source='term.academic_year.name')
    class_rooms = ClassRoomSerializer(source='department.class_rooms', many=True)

    class Meta:
        model = SubjectAssignment
        fields = [
            'id', 'subject', 'teacher', 'department',
            'term', 'academic_year', 'class_rooms'
        ]


class SubjectAssignmentSerializer(serializers.ModelSerializer):
    class Meta:
        model = SubjectAssignment
        fields = [
            'id', 'subject', 'teacher', 'department',
            'term', 'coefficient'
        ]

    def validate(self, data):
        # Ensure teacher teaches this subject
        if data['teacher'].taught_subjects.filter(id=data['subject'].id).exists() is False:
            raise serializers.ValidationError("Teacher must be assigned to this subject")
        return data
    
class MarkSerializer(serializers.ModelSerializer):
    student = serializers.CharField(source='student.user.get_full_name')
    subject = serializers.CharField(source='subject_assignment.subject.name')
    department = serializers.CharField(source='subject_assignment.department.name')
    term = serializers.CharField(source='subject_assignment.term.name')

    class Meta:
        model = Mark
        fields = [
            'id', 'student', 'subject', 'department', 'term',
            'score', 'total_mark', 'comment', 'entered_at'
        ]
        read_only_fields = ['total_mark', 'entered_at']


class MarkCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Mark
        fields = ['student', 'subject_assignment', 'score', 'comment']

    def validate_score(self, value):
        assignment = self.initial_data.get('subject_assignment')
        if assignment:
            try:
                subj = SubjectAssignment.objects.get(id=assignment).subject
                if value > subj.max_score:
                    raise serializers.ValidationError(f"Score exceeds max ({subj.max_score})")
            except SubjectAssignment.DoesNotExist:
                pass
        return value