from adrf.viewsets import ModelViewSet
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework import status
from asgiref.sync import sync_to_async
from django.contrib.auth import get_user_model
from .models import AcademicYear, Term, ClassRoom, Mark
from .serializers import *
from .permissions import IsPrincipal  # Reuse from earlier

User = get_user_model()


class AcademicYearViewSet(ModelViewSet):
    queryset = AcademicYear.objects.all().order_by('-id')
    serializer_class = AcademicYearSerializer
    permission_classes = [IsPrincipal]  # Only principal

    @action(detail=False, methods=['post'], url_path='set-current')
    async def set_current(self, request):
        """POST /api/academic-year/set-current/ { "id": "uuid" }"""
        year_id = request.data.get('id')
        if not year_id:
            return Response({"error": "id required"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            year = await AcademicYear.objects.aget(id=year_id)
        except AcademicYear.DoesNotExist:
            return Response({"error": "Not found"}, status=status.HTTP_404_NOT_FOUND)

        # Clear current
        await AcademicYear.objects.filter(is_current=True).aupdate(is_current=False)
        # Set new
        year.is_current = True
        await year.asave()

        return Response({
            "message": "Current academic year updated",
            "current_year": year.name
        })
    
class TermViewSet(ModelViewSet):
    """
    POST   /api/terms/set-current/     → set_current
    GET    /api/terms/?academic_year=uuid
    """
    queryset = Term.objects.all()
    serializer_class = TermSerializer
    permission_classes = [IsPrincipal]

    def get_queryset(self):
        queryset = Term.objects.select_related('academic_year').order_by(
            'academic_year__start_date', 'term_number'
        )
        year_id = self.request.query_params.get('academic_year')
        if year_id:
            queryset = queryset.filter(academic_year_id=year_id)
        return queryset

    # --- ASYNC CREATE ---
    async def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        await sync_to_async(serializer.is_valid)(raise_exception=True)
        await self._validate_unique_term(serializer.validated_data)
        await sync_to_async(serializer.save)()
        return Response(serializer.data, status=201)

    # --- ASYNC UPDATE ---
    async def update(self, request, *args, **kwargs):
        partial = kwargs.pop('partial', False)
        instance = await self.aget_object()
        serializer = self.get_serializer(instance, data=request.data, partial=partial)
        await sync_to_async(serializer.is_valid)(raise_exception=True)
        await self._validate_unique_term(serializer.validated_data, instance=instance)
        await sync_to_async(serializer.save)()
        return Response(serializer.data)

    # --- Shared validation ---
    async def _validate_unique_term(self, data, instance=None):
        year = data['academic_year']
        number = data['term_number']
        exclude_id = instance.id if instance else None

        exists = await Term.objects.filter(
            academic_year=year,
            term_number=number
        ).exclude(pk=exclude_id).aexists()

        if exists:
            raise ValidationError(f"Term {number} already exists in {year}")

    # --- SET CURRENT TERM ---
    @action(detail=False, methods=['post'], url_path='set-current')
    async def set_current(self, request):
        """
        POST /api/terms/set-current/
        { "id": "uuid" }
        """
        term_id = request.data.get('id')
        if not term_id:
            return Response({"error": "id required"}, status=400)

        try:
            term = await Term.objects.select_related('academic_year').aget(id=term_id)
        except Term.DoesNotExist:
            return Response({"error": "Term not found"}, status=404)

        # Clear current
        await Term.objects.filter(is_current=True).aupdate(is_current=False)
        # Set new
        term.is_current = True
        await term.asave()

        return Response({
            "message": "Current term updated",
            "current_term": term.name,
            "academic_year": term.academic_year.name
        })
    
class ClassRoomViewSet(ModelViewSet):
    queryset = ClassRoom.objects.all().order_by('name')
    serializer_class = ClassRoomSerializer
    permission_classes = [IsPrincipal]

class SubjectViewSet(ModelViewSet):
    queryset = Subject.objects.all().order_by('code')
    serializer_class = SubjectSerializer
    permission_classes = [IsPrincipal]  # Only principal

class SubjectAssignmentViewSet(ModelViewSet):
    queryset = SubjectAssignment.objects.all()
    permission_classes = [IsPrincipal]
    serializer_class = SubjectAssignmentSerializer

    def get_queryset(self):
        queryset = SubjectAssignment.objects.select_related(
            'subject', 'teacher', 'department', 'term', 'term__academic_year'
        ).prefetch_related('department__class_rooms')
        return queryset.order_by(
            'term__academic_year__start_date',
            'term__term_number',
            'department__name'
        )

    def get_serializer_class(self):
        if self.action == 'list':
            return SubjectAssignmentListSerializer
        return SubjectAssignmentSerializer

    @action(detail=False, methods=['get'])
    async def by_teacher(self, request):
        """GET /api/subject-assignments/by-teacher/?teacher_id=uuid"""
        teacher_id = request.query_params.get('teacher_id')
        if not teacher_id:
            return Response({"error": "teacher_id required"}, status=400)

        try:
            teacher = await User.objects.aget(id=teacher_id, role='teacher')
        except User.DoesNotExist:
            return Response({"error": "Teacher not found"}, status=404)

        assignments = await asyncio.to_thread(
            lambda: list(self.get_queryset().filter(teacher=teacher))
        )
        serializer = SubjectAssignmentListSerializer(assignments, many=True)
        return Response(serializer.data)
    
class MarkViewSet(ModelViewSet):
    queryset = Mark.objects.all()

    def get_queryset(self):
        user = self.request.user
        queryset = Mark.objects.select_related(
            'student', 'subject_assignment', 'subject_assignment__subject',
            'subject_assignment__department', 'subject_assignment__term'
        )

        if user.role == 'principal':
            return queryset
        elif user.role == 'teacher':
            return queryset.filter(
                subject_assignment__teacher=user
            )
        elif user.role == 'student':
            return queryset.filter(student__user=user)
        else:
            return queryset.none()

    def get_serializer_class(self):
        if self.action in ['create', 'update', 'partial_update']:
            return MarkCreateSerializer
        return MarkSerializer

    def perform_create(self, serializer):
        # Auto-set entered_by
        serializer.save(entered_by=self.request.user)

    @action(detail=False, methods=['post'])
    async def bulk_upsert(self, request):
        """
        POST /api/marks/bulk-upsert/
        [
          { "student_id": "...", "assignment_id": "...", "score": 18.5, "comment": "Good" }
        ]
        """
        data = request.data
        if not isinstance(data, list):
            return Response({"error": "Expected array"}, status=400)

        errors = []
        created = 0
        updated = 0

        for i, item in enumerate(data):
            serializer = MarkCreateSerializer(data=item)
            if not serializer.is_valid():
                errors.append({f"row {i+1}": serializer.errors})
                continue

            student_id = item['student_id']
            assignment_id = item['assignment_id']

            mark, was_created = await Mark.objects.aupdate_or_create(
                student_id=student_id,
                subject_assignment_id=assignment_id,
                defaults={
                    'score': item['score'],
                    'comment': item.get('comment', ''),
                    'entered_by': request.user
                }
            )
            if was_created:
                created += 1
            else:
                updated += 1

        response = {
            "created": created,
            "updated": updated,
            "errors": errors
        }
        return Response(response, status=200 if not errors else 400)