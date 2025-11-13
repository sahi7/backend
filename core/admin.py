# apps/core/admin.py
from django.contrib import admin
from django.utils.html import format_html
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from . import models

# class MyAdminSite(admin.AdminSite):
#     def get_app_list(self, request):
#         app_list = super().get_app_list(request)
#         return app_list

#     @property
#     def site_header(self):
#         return "RCMS Admin"

# admin.site = MyAdminSite(name='rcms_admin')
# admin.site.site_title = "RCMS"
# admin.site.index_title = "Dashboard"

# Add CSS
# admin.site.index_template = 'admin/custom_index.html'

# === AcademicYear ===
@admin.register(models.AcademicYear)
class AcademicYearAdmin(admin.ModelAdmin):
    list_display = ('name', 'start_date', 'end_date', 'is_current', 'term_count')
    list_filter = ('is_current', 'start_date')
    search_fields = ('name',)
    ordering = ('-start_date',)
    date_hierarchy = 'start_date'
    readonly_fields = ('created_at',)

    def term_count(self, obj):
        count = obj.terms.count()
        url = f"/admin/core/term/?academic_year__id__exact={obj.pk}"
        return format_html('<a href="{}">{}</a>', url, count)
    term_count.short_description = "Terms"

    fieldsets = (
        ("Academic Year", {
            'fields': ('name', 'start_date', 'end_date', 'is_current')
        }),
        ("Metadata", {
            'fields': ('created_at',),
            'classes': ('collapse',)
        }),
    )


# === Term ===
@admin.register(models.Term)
class TermAdmin(admin.ModelAdmin):
    list_display = ('name', 'academic_year', 'term_number', 'start_date', 'end_date')
    list_filter = ('academic_year', 'term_number')
    search_fields = ('name', 'academic_year__name')
    ordering = ('academic_year', 'term_number')

    def get_queryset(self, request):
        return super().get_queryset(request).select_related('academic_year')


# === ClassRoom ===
@admin.register(models.ClassRoom)
class ClassRoomAdmin(admin.ModelAdmin):
    list_display = ('name', 'department_count')
    search_fields = ('name',)
    ordering = ('name',)

    def department_count(self, obj):
        count = obj.departments.count()
        return format_html('<b style="color:#1976d2">{}</b>', count)
    department_count.short_description = "Departments"


# === Department ===
@admin.register(models.Department)
class DepartmentAdmin(admin.ModelAdmin):
    list_display = ('name', 'slug', 'classroom_list', 'student_count')
    list_filter = ('class_rooms__name',)
    search_fields = ('name', 'slug')
    prepopulated_fields = {'slug': ('name',)}
    filter_horizontal = ('class_rooms',)

    def classroom_list(self, obj):
        rooms = obj.class_rooms.all()[:3]
        html = ", ".join([f"<b>{r.name}</b>" for r in rooms])
        if obj.class_rooms.count() > 3:
            html += f" <i>(+{obj.class_rooms.count() - 3} more)</i>"
        return format_html(html)
    classroom_list.short_description = "Classes"

    def student_count(self, obj):
        from core.models import Student
        count = Student.objects.filter(department=obj).count()
        return format_html('<span style="color:green;font-weight:bold">{}</span>', count)
    student_count.short_description = "Students"

@admin.register(models.User)
class UserAdmin(BaseUserAdmin):
    list_display = ('username', 'email', 'full_name', 'role', 'department', 'is_active')
    list_filter = ('role', 'is_active', 'department', 'date_joined')
    search_fields = ('username', 'email', 'first_name', 'last_name')
    ordering = ('-date_joined',)

    fieldsets = (
        ("Login", {'fields': ('username', 'password')}),
        ("Personal Info", {'fields': ('first_name', 'last_name', 'email')}),
        ("Role & Access", {'fields': ('role', 'department', 'taught_subjects')}),
        ("Permissions", {'fields': ('is_active', 'is_staff', 'is_superuser', 'groups', 'user_permissions')}),
        ("Dates", {'fields': ('last_login', 'date_joined')}),
    )

    add_fieldsets = (
        (None, {
            'fields': ('username', 'email', 'password1', 'password2', 'role', 'department'),
        }),
    )

    filter_horizontal = ('taught_subjects', 'groups', 'user_permissions')

    def full_name(self, obj):
        name = obj.get_full_name()
        return name or "—"
    full_name.short_description = "Name"

@admin.register(models.Subject)
class SubjectAdmin(admin.ModelAdmin):
    list_display = ('code', 'name', 'coefficient', 'max_score', 'department_count', 'teacher_count')
    list_filter = ('coefficient', 'max_score')
    search_fields = ('name', 'code')
    ordering = ('code',)

    filter_horizontal = ('departments',)

    def department_count(self, obj):
        count = obj.departments.count()
        return format_html('<b style="color:#d32f2f">{}</b>', count)
    department_count.short_description = "Depts"

    def teacher_count(self, obj):
        count = obj.teachers.count()
        return format_html('<b style="color:#388e3c">{}</b>', count)
    teacher_count.short_description = "Teachers"

@admin.register(models.Student)
class StudentAdmin(admin.ModelAdmin):
    list_display = ('registration_number', 'full_name', 'department', 'current_class', 'average_grade')
    list_filter = ('department', 'current_class')
    search_fields = ('registration_number', 'user__first_name', 'user__last_name')
    raw_id_fields = ('user', 'department', 'current_class')

    def full_name(self, obj):
        return obj.user.get_full_name() or obj.user.username
    full_name.short_description = "Name"

    def average_grade(self, obj):
        avg = obj.marks.aggregate(avg=models.Avg('total_mark'))['avg']
        if avg is not None:
            color = "green" if avg >= 50 else "red"
            return format_html('<b style="color:{}">{:.1f}</b>', color, avg)
        return "—"
    average_grade.short_description = "Avg Mark"


@admin.register(models.SubjectAssignment)
class SubjectAssignmentAdmin(admin.ModelAdmin):
    list_display = ('subject', 'department', 'term', 'teacher')
    list_filter = ('term', 'department', 'subject')
    search_fields = ('subject__name', 'subject__code', 'teacher__username')
    raw_id_fields = ('teacher',)


@admin.register(models.Mark)
class MarkAdmin(admin.ModelAdmin):
    list_display = ('student', 'subject', 'score', 'total_mark', 'comment_preview', 'entered_by', 'modified_at')
    list_filter = ('subject_assignment__subject', 'subject_assignment__term', 'entered_by')
    search_fields = ('student__registration_number', 'subject_assignment__subject__name')
    readonly_fields = ('total_mark', 'entered_at', 'modified_at')
    raw_id_fields = ('student', 'subject_assignment', 'entered_by', 'modified_by')

    def comment_preview(self, obj):
        if obj.comment:
            return obj.comment[:30] + ("..." if len(obj.comment) > 30 else "")
        return "—"
    comment_preview.short_description = "Comment"

    def subject(self, obj):
        return obj.subject_assignment.subject
    subject.short_description = "Subject"
