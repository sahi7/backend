# apps/users/views.py (continued)
import secrets
import string
import asyncio
from adrf.views import APIView
from rest_framework_simplejwt.views import TokenRefreshView, TokenObtainPairView
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from django.contrib.auth import get_user_model

from utils.user import send_welcome_email
from .permissions import IsPrincipal
from .serializers import CustomTokenObtainPairSerializer
User = get_user_model()

class CustomTokenObtainPairView(TokenObtainPairView):
    serializer_class = CustomTokenObtainPairSerializer

    def post(self, request, *args, **kwargs):
        response = super().post(request, *args, **kwargs)

        # Set refresh token in httpOnly cookie
        response.set_cookie(
            key='refresh_token',
            value=response.data['refresh'],
            httponly=True,
            secure=True,                    # HTTPS only
            samesite='Strict',
            max_age=7 * 24 * 60 * 60,       # 7 days
            path='/api/auth/refresh/',      # Only available on refresh endpoint
        )

        # Remove refresh from JSON response
        response.data.pop('refresh', None)

        # Return access token + user in body (React reads this once)
        return response

class CustomTokenRefreshView(TokenRefreshView):
    permission_classes = [AllowAny]

    def post(self, request, *args, **kwargs):
        # Read refresh token from cookie
        refresh_token = request.COOKIES.get('refresh_token')
        if not refresh_token:
            return Response({"error": "No refresh token"}, status=400)

        request.data['refresh'] = refresh_token
        response = super().post(request, *args, **kwargs)

        # Optional: rotate cookie
        response.set_cookie(
            key='refresh_token',
            value=response.data['refresh'],
            httponly=True,
            secure=True,
            samesite='Strict',
            max_age=7 * 24 * 60 * 60,
            path='/api/auth/refresh/',
        )
        response.data.pop('refresh', None)

        return response
    
class ResendWelcomeEmailView(APIView):
    permission_classes = [IsPrincipal,]
    
    async def post(self, request):
        user_id = request.data.get('user_id')
        if not user_id:
            return Response({"error": "user_id required"}, status=400)

        try:
            user = await User.objects.aget(id=user_id)
        except User.DoesNotExist:
            return Response({"error": "User not found"}, status=404)

        # Generate new temp password
        temp_password = ''.join(secrets.choice(string.ascii_letters + string.digits) for _ in range(12))
        await user.aset_password(temp_password)
        await user.asave()

        # Send
        asyncio.create_task(send_welcome_email(user, temp_password))

        return Response({
            "message": "Welcome email resent",
            "user": user.email,
            "temp_password": temp_password  # Remove in prod!
        })