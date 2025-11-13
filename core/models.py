from django.contrib.auth.models import AbstractUser
from django.db import models
import uuid

class User(AbstractUser):
    ROLE_CHOICES = [
        ('principal', 'Principal'),
        ('teacher', 'Teacher'),
        ('student', 'Student'),
        ('parent', 'Parent'),
    ]
    role = models.CharField(max_length=20, choices=ROLE_CHOICES)
    department = models.ForeignKey('Department', null=True, blank=True, on_delete=models.SET_NULL)
    taught_subjects = models.ManyToManyField('Subject', blank=True, related_name='teachers')
    # Phone_number = models.CharField(max_length=10)

    def get_full_name(self):
        return f"{self.first_name} {self.last_name}"

    async def can_edit_marks(self, subject, department):
        if self.role == 'principal':
            return True
        if self.role == 'teacher':
            is_taught = await self.taught_subjects.filter(pk=subject.pk).aexists()
            if is_taught:
                assignment = await SubjectAssignment.objects.filter(
                    subject=subject, department=department, teacher=self
                ).aexists()
                return assignment
        return False
    
    def __str__(self):
        return self.get_full_name()

class AcademicYear(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4)
    name = models.CharField(max_length=20, unique=True)  # e.g., "2025/2026"
    start_date = models.DateField()
    end_date = models.DateField()
    is_current = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name

class Term(models.Model):
    TERM_CHOICES = [(1, 'Term 1'), (2, 'Term 2'), (3, 'Term 3')]
    academic_year = models.ForeignKey(AcademicYear, on_delete=models.CASCADE)
    term_number = models.IntegerField(choices=TERM_CHOICES)
    name = models.CharField(max_length=20)
    is_current = models.BooleanField(default=False)
    start_date = models.DateField()
    end_date = models.DateField()

    class Meta:
        unique_together = ('academic_year', 'term_number')

    def __str__(self):
        return f"{self.academic_year} - {self.name}"

class ClassRoom(models.Model):
    name = models.CharField(max_length=20)  # e.g., "Form 1", "Form 2"

    def __str__(self):
        return self.name

class Department(models.Model):
    name = models.CharField(max_length=50)  # "Electricity", "Building", "Accounting"
    class_rooms = models.ManyToManyField(ClassRoom, null=True, related_name='departments')
    student_count = models.IntegerField(default=0)

    def __str__(self):
        return self.name

# apps/marks/models.py
class Student(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    registration_number = models.CharField(max_length=20, unique=True)
    department = models.ForeignKey(Department, on_delete=models.PROTECT)
    current_class = models.ForeignKey(ClassRoom, on_delete=models.PROTECT)

    def __str__(self):
        return self.registration_number
    
class Subject(models.Model):
    name = models.CharField(max_length=100)
    code = models.CharField(max_length=10, unique=True)  # e.g., "ELEC101"
    coefficient = models.DecimalField(max_digits=4, decimal_places=2, default=1.0)
    departments = models.ManyToManyField(Department, through='SubjectAssignment')
    max_score = models.DecimalField(max_digits=5, decimal_places=2, default=100.0)

    def __str__(self):
        return f"{self.code} - {self.name}"

class SubjectAssignment(models.Model):
    subject = models.ForeignKey(Subject, on_delete=models.CASCADE)
    department = models.ForeignKey(Department, on_delete=models.CASCADE)
    teacher = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    term = models.ForeignKey(Term, on_delete=models.CASCADE, null=True)

    class Meta:
        unique_together = ('subject', 'department', 'term')

class Mark(models.Model):
    student = models.ForeignKey(Student, on_delete=models.CASCADE)
    subject_assignment = models.ForeignKey(SubjectAssignment, on_delete=models.CASCADE)
    score = models.DecimalField(max_digits=5, decimal_places=2)  # out of max_score
    total_mark = models.DecimalField(max_digits=6, decimal_places=2, editable=False)  # score * coeff
    comment = models.TextField(blank=True)
    entered_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    entered_at = models.DateTimeField(auto_now_add=True)
    modified_by = models.ForeignKey(User, related_name='modified_marks', null=True, on_delete=models.SET_NULL)
    modified_at = models.DateTimeField(null=True)

    def save(self, *args, **kwargs):
        self.total_mark = self.score * self.subject_assignment.subject.coefficient
        super().save(*args, **kwargs)