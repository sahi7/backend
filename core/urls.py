from django.urls import path, include
from .custom_views import *
from .views import *
from .model_views import *
from rest_framework.routers import DefaultRouter

router = DefaultRouter()
router.register(r'academic-years', AcademicYearViewSet)
router.register(r'terms', TermViewSet)
router.register(r'classrooms', ClassRoomViewSet)
router.register(r'subjects', SubjectViewSet)
router.register(r'subject-assignments', SubjectAssignmentViewSet)
router.register(r'', MarkViewSet)

urlpatterns = [
    path('import/', ExcelMarkImportView.as_view(), name='mark-import'),
    path('teacher-scope/<str:teacher_id>/', TeacherScopeView.as_view(), name='teacher-scope'),
    path('marks/bulk-upsert/', MarkViewSet.as_view({'post': 'bulk_upsert'}), name='mark-bulk'),
    # path('subjects/', include('apps.subjects.urls')),
    # path('assignments/', include('apps.marks.urls')),
    
    path('auth/register/', RegisterUserView.as_view(), name='register'),
    path('auth/resend-welcome/', ResendWelcomeEmailView.as_view(), name='resend-welcome'),
    path('auth/me/', UserMeView.as_view(), name='me'),
    path('auth/change-password/', ChangePasswordView.as_view(), name='change-password'),
    path('auth/forgot-password/', ForgotPasswordView.as_view(), name='forgot-password'),
    path('auth/reset-password/<str:uidb64>/<str:token>/', ResetPasswordView.as_view(), name='reset-password'),
    path('auth/logout/', LogoutView.as_view(), name='logout'),

    path('', include(router.urls)),
]