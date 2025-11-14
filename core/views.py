# marks/views.py
import pandas as pd
import openpyxl
import asyncio
import secrets
import string
from typing import List
from django.contrib.auth import get_user_model
from openpyxl.utils.exceptions import InvalidFileException
from adrf.views import APIView
from rest_framework.response import Response
from rest_framework import status
from asgiref.sync import sync_to_async

from.permissions import *
from .models import Department
from .custom_views import send_welcome_email
from .models import Mark, Student, Subject, SubjectAssignment, Term
import logging

logger = logging.getLogger('web')
User = get_user_model()

class RegisterUserView(APIView):
    """
    Create teacher/student/parent (Principal only).

    **Request**
    ```json
    POST /api/users/register/
    {
      "role": "teacher",
      "email": "new@school.cm",
      "first_name": "Jane",
      "last_name": "Smith",
      "department_id": "uuid-dept-1",
      "subject_ids": ["uuid-subj-1", "uuid-subj-2"]
    }
    """
    permission_classes = [IsPrincipal]

    async def post(self, request):
        data = request.data
        role = data.get('role')
        email = data.get('email', '').strip().lower()
        first_name = data.get('first_name', '').strip()
        last_name = data.get('last_name', '').strip()

        if role not in ['teacher', 'student', 'parent']:
            return Response({"error": "Invalid role"}, status=status.HTTP_400_BAD_REQUEST)

        if not email or not (first_name or last_name):
            return Response({"error": "Email and name required"}, status=status.HTTP_400_BAD_REQUEST)

        # Check duplicate
        if await User.objects.filter(email=email).aexists():
            return Response({"error": "Email already exists"}, status=status.HTTP_400_BAD_REQUEST)

        # Generate temp password
        temp_password = ''.join(secrets.choice(string.ascii_letters + string.digits) for _ in range(12))

        # Create user
        user = await User.objects.acreate(
            username=email,
            email=email,
            first_name=first_name,
            last_name=last_name,
            role=role,
            is_active=True
        )
        await sync_to_async(user.set_password)(temp_password)

        # Assign department (for teacher/student)
        department_id = data.get('department_id')
        if department_id and role in ['teacher', 'student']:
            try:
                department = await Department.objects.aget(id=department_id)
                user.department = department
            except Department.DoesNotExist:
                return Response({"error": "Department not found"}, status=400)

        # Assign subjects (teacher only)
        subject_ids = data.get('subject_ids', [])
        if role == 'teacher' and subject_ids:
            subjects = await Subject.objects.filter(id__in=subject_ids).ain_bulk()
            await user.taught_subjects.aadd(*subjects.values())

        await user.asave() 

        # Send email (async offload)
        asyncio.create_task(send_welcome_email(user, temp_password))
        print("User: ", user)

        return Response({
            "message": "User created",
            "user": {
                "id": str(user.id),
                "email": user.email,
                "name": user.get_full_name(),
                "role": user.role,
                "temp_password": temp_password  # Only in dev!
            }
        }, status=status.HTTP_201_CREATED)

def _commit_marks_sync(
        marks_to_create: List[Mark],
        marks_to_update: List[Mark],
    ):
        from django.db import transaction

        with transaction.atomic():
            if marks_to_create:
                Mark.objects.bulk_create(
                    marks_to_create,
                    update_conflicts=True,
                    update_fields=['score', 'total_mark', 'comment', 'entered_by', 'modified_by'],
                    unique_fields=['student', 'subject_assignment'],
                )
            if marks_to_update:
                Mark.objects.bulk_update(
                    marks_to_update,
                    ['score', 'total_mark', 'comment', 'entered_by', 'modified_by', 'modified_at'],
                )

class UserMeView(APIView):
    """
    Return authenticated user profile.

    **Request**
    ```http
    GET /api/auth/me/
    Authorization: Bearer <access_token>
    """
    permission_classes = []

    async def get(self, request):
        user = request.user
        return Response({
            "id": str(user.id),
            "email": user.email,
            "full_name": user.get_full_name(),
            "role": user.role,
            "department": user.department.name if user.department else None,
        })
    
class ExcelMarkImportView(APIView):
    """
    POST: Upload Excel/CSV with marks
    Required fields in file: student_number, subject_name, subject_code, score, comment
    Teacher auto-resolved from SubjectAssignment
    """
    permission_classes = []  # Add your auth later

    async def post(self, request):
        file = request.data.get('file')
        term_id = request.data.get('term_id')
        assignment_id = request.data.get('assignment_id')  # Optional: if teacher uploads for one subject

        if not file:
            return Response({"error": "No file uploaded"}, status=status.HTTP_400_BAD_REQUEST)

        if not term_id:
            return Response({"error": "term_id is required"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            term = await Term.objects.aget(id=term_id)
        except Term.DoesNotExist:
            return Response({"error": "Invalid term_id"}, status=status.HTTP_400_BAD_REQUEST)

        # Read file async (offload to thread)
        try:
            df = await asyncio.to_thread(self._read_excel_file, file)
        except Exception as e:
            logger.error(f"File read error: {e}")
            return Response({"error": "Invalid file format. Use .xlsx or .csv"}, status=status.HTTP_400_BAD_REQUEST)

        # Validate columns
        required_cols = {'student_number', 'subject_name', 'subject_code', 'score', 'comment'}
        if not required_cols.issubset(set(df.columns.str.lower())):
            missing = required_cols - set(df.columns.str.lower())
            return Response({
                "error": f"Missing columns: {', '.join(missing)}",
                "required": list(required_cols)
            }, status=status.HTTP_400_BAD_REQUEST)

        # Normalize column names
        df.columns = [col.strip().lower() for col in df.columns]
        df = df[required_cols].copy()

        # Clean data
        df['student_number'] = df['student_number'].astype(str).str.strip()
        df['subject_code'] = df['subject_code'].astype(str).str.strip().str.upper()
        df['score'] = pd.to_numeric(df['score'], errors='coerce')
        df['comment'] = df['comment'].astype(str).str.strip().replace({'nan': ''})

        # Filter valid rows
        valid_rows = df.dropna(subset=['student_number', 'subject_code', 'score'])
        invalid_rows = df[df.isna().any(axis=1)][['student_number', 'subject_code', 'score']]

        errors = []
        if not invalid_rows.empty:
            errors.append(f"Rows with missing data (skipped): {len(invalid_rows)}")

        if valid_rows.empty:
            return Response({
                "success": False,
                "message": "No valid data to import",
                "errors": errors
            }, status=status.HTTP_400_BAD_REQUEST)

        # Pre-fetch students and subjects
        student_numbers = valid_rows['student_number'].unique().tolist()
        subject_codes = valid_rows['subject_code'].unique().tolist()

        students = await Student.objects.ain_bulk(
            field_name='registration_number',
            objects=await Student.objects.filter(registration_number__in=student_numbers).aprefetch_related('department')
        )
        subjects = await Subject.objects.ain_bulk(
            field_name='code',
            objects=await Subject.objects.filter(code__in=subject_codes)
        )

        # Pre-fetch assignments for this term
        assignments_qs = SubjectAssignment.objects.filter(
            term=term,
            subject__code__in=subject_codes
        ).select_related('subject', 'department', 'teacher')

        if assignment_id:
            assignments_qs = assignments_qs.filter(id=assignment_id)

        assignments = {
            (a.subject.code, a.department.id): a
            for a in await assignments_qs
        }

        marks_to_create = []
        marks_to_update = []
        row_errors = []

        # Process each row
        for idx, row in valid_rows.iterrows():
            reg_no = row['student_number']
            code = row['subject_code']
            score = row['score']
            comment = row['comment'] if row['comment'] else ""

            # Validate student
            student = students.get(reg_no)
            if not student:
                row_errors.append(f"Row {idx+2}: Student {reg_no} not found")
                continue

            # Validate subject
            subject = subjects.get(code)
            if not subject:
                row_errors.append(f"Row {idx+2}: Subject code {code} not found")
                continue

            # Validate score range
            if not (0 <= score <= subject.max_score):
                row_errors.append(f"Row {idx+2}: Score {score} out of range (0–{subject.max_score})")
                continue

            # Resolve assignment: subject + department + term
            dept_id = student.department.id
            assignment_key = (code, dept_id)
            assignment = assignments.get(assignment_key)

            if not assignment:
                row_errors.append(f"Row {idx+2}: No assignment for {code} in {student.department}")
                continue

            # Check teacher permission (if not principal)
            if not await asyncio.to_thread(
                request.user.can_edit_marks, assignment.subject, assignment.department
            ):
                row_errors.append(f"Row {idx+2}: You cannot edit {code} in {student.department}")
                continue

            # Check existing mark
            existing = await Mark.objects.filter(
                student=student,
                subject_assignment=assignment
            ).afirst()

            total_mark = score * assignment.subject.coefficient

            mark_data = {
                'student': student,
                'subject_assignment': assignment,
                'score': score,
                'total_mark': total_mark,
                'comment': comment[:500],
                'entered_by': request.user,
            }

            if existing:
                # Update
                for k, v in mark_data.items():
                    setattr(existing, k, v)
                existing.modified_by = request.user
                existing.modified_at = None  # auto_now
                marks_to_update.append(existing)
            else:
                mark_data['modified_by'] = None
                marks_to_create.append(Mark(**mark_data))

        # Final response before DB
        if row_errors:
            return Response({
                "success": False,
                "message": f"{len(row_errors)} validation errors",
                "errors": row_errors[:50],  # limit
                "preview": {
                    "to_create": len(marks_to_create),
                    "to_update": len(marks_to_update)
                }
            }, status=status.HTTP_400_BAD_REQUEST)

        # Atomic DB write
        try:
            await asyncio.to_thread(
                _commit_marks_sync,
                marks_to_create,
                marks_to_update,
            )
        except Exception as e:
            logger.exception("Import failed")
            return Response({
                "success": False,
                "error": "Database error during import",
                "detail": str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        logger.info(f"Marks import by {request.user}: {len(marks_to_create)} created, {len(marks_to_update)} updated")

        return Response({
            "success": True,
            "message": "Import completed",
            "created": len(marks_to_create),
            "updated": len(marks_to_update),
            "skipped": len(row_errors)
        }, status=status.HTTP_201_CREATED)
    
    

    def _read_excel_file(self, file_obj) -> pd.DataFrame:
        """Sync helper: read Excel/CSV"""
        if file_obj.name.endswith('.csv'):
            return pd.read_csv(file_obj)
        elif file_obj.name.endswith(('.xls', '.xlsx')):
            try:
                return pd.read_excel(file_obj, engine='openpyxl')
            except InvalidFileException:
                raise ValueError("Invalid Excel file")
        else:
            raise ValueError("Unsupported file type")
        
class TeacherScopeView(APIView):
    """
    GET /api/teacher-scope/<teacher_id>/
    Returns full hierarchical scope of a teacher.
    Only accessible by principal or the teacher themselves.
    """
    permission_classes = [CanViewTeacherScope, ]  # Add later: IsAuthenticated + custom

    async def get(self, request, teacher_id: str):
        # 1. Fetch teacher
        try:
            teacher = await User.objects.aget(id=teacher_id, role='teacher')
        except (ValueError, User.DoesNotExist):
            return Response(
                {"error": "Teacher not found or invalid ID"},
                status=status.HTTP_404_NOT_FOUND
            )

        # 2. Authorization
        if request.user.id != teacher.id and request.user.role != 'principal':
            return Response(
                {"error": "Unauthorized"},
                status=status.HTTP_403_FORBIDDEN
            )

        # 3. Fetch assignments with prefetch (async-safe)
        assignments = await asyncio.to_thread(
            lambda: list(
                SubjectAssignment.objects.filter(teacher=teacher)
                .select_related(
                    'subject',
                    'term',
                    'term__academic_year',
                    'department'
                )
                .prefetch_related(
                    'department__class_rooms'  # M2M → now works
                )
                .order_by(
                    'term__academic_year__start_date',
                    'term__term_number',
                    'department__class_rooms__name',
                    'department__name',
                    'subject__code'
                )
            )
        )

        if not assignments:
            return Response({
                "teacher": {
                    "id": str(teacher.id),
                    "full_name": teacher.get_full_name() or teacher.username,
                    "username": teacher.username
                },
                "scope": {},
                "summary": {
                    "total_assignments": 0,
                    "unique_subjects": 0,
                    "classes": [],
                    "departments": []
                }
            })

        # 4. Build nested scope: Year → Term → Class → Dept → [Subjects]
        scope = defaultdict(lambda: defaultdict(lambda: defaultdict(lambda: defaultdict(list))))
        seen_classes = set()
        seen_depts = set()
        seen_subjects = set()

        for assignment in assignments:
            year = assignment.term.academic_year.name
            term = assignment.term.name
            subject = assignment.subject
            dept = assignment.department

            # Get all class names from M2M
            class_names = [cr.name for cr in dept.class_rooms.all()]
            dept_name = dept.name

            for class_name in class_names:
                scope[year][term][class_name][dept_name].append({
                    "assignment_id": str(assignment.id),
                    "subject_code": subject.code,
                    "subject_name": subject.name,
                    "coefficient": float(subject.coefficient),
                    "max_score": float(subject.max_score),
                })

                seen_classes.add(class_name)
                seen_depts.add(dept_name)
                seen_subjects.add(subject.code)

        # Convert to plain dict
        scope_dict = {
            year: {
                term: {
                    cls: {
                        dept: subjects
                        for dept, subjects in dept_dict.items()
                    }
                    for cls, dept_dict in cls_dict.items()
                }
                for term, cls_dict in term_dict.items()
            }
            for year, term_dict in scope.items()
        }

        # 5. Response
        return Response({
            "teacher": {
                "id": str(teacher.id),
                "full_name": teacher.get_full_name() or teacher.username,
                "username": teacher.username
            },
            "scope": scope_dict,
            "summary": {
                "total_assignments": len(assignments),
                "unique_subjects": len(seen_subjects),
                "classes": sorted(seen_classes),
                "departments": sorted(seen_depts)
            }
        })