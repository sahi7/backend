from django.urls import path
from .custom_views import ResendWelcomeEmailView
from .views import *

urlpatterns = [
    path('import/', ExcelMarkImportView.as_view(), name='mark-import'),
    path('teacher-scope/<uuid:teacher_id>/', TeacherScopeView.as_view(), name='teacher-scope'),
    path('auth/register/', RegisterUserView.as_view(), name='register'),
    path('resend-welcome/', ResendWelcomeEmailView.as_view(), name='resend-welcome'),
]