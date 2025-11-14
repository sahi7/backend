# apps/users/views.py (continued)
import uuid
import secrets
import string
import asyncio
from asgiref.sync import sync_to_async
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
    """
    Login user and return access token + user details.
    Sets `refresh_token` in httpOnly cookie.

    **Request**
    ```json
    POST /api/auth/login/
    {
      "email": "teacher@school.cm",
      "password": "MyPass123"
    }
    """
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
    """
    Refresh access token using httpOnly cookie.

    **Request**
    ```json
    POST /api/auth/refresh/
    {}  // No body — reads cookie
    """
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
    """
    Resend welcome email with new temp password.

    **Request**
    ```json
    POST /api/auth/resend-welcome/
    {
      "user_id": "uuid-456"
    }
    """
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
        await sync_to_async(user.set_password)(temp_password)
        await user.asave()

        # Send
        asyncio.create_task(send_welcome_email(user, temp_password))

        return Response({
            "message": "Welcome email resent",
            "user": user.email,
            "temp_password": temp_password  # Remove in prod!
        })
    
class ChangePasswordView(APIView):
    """
    Change password for authenticated user.

    **Request**
    ```json
    POST /api/auth/change-password/
    {
      "old_password": "MyPass123",
      "new_password": "NewPass456!"
    }
    """

    async def post(self, request):
        old = request.data.get('old_password')
        new = request.data.get('new_password')

        if not old or not new:
            return Response({"error": "Both passwords required"}, status=400)

        user = request.user
        if not await sync_to_async(user.check_password)(old):
            return Response({"error": "Incorrect old password"}, status=400)

        await sync_to_async(user.set_password)(new)
        await user.asave()

        return Response({"message": "Password changed"})

from django.conf import settings
from django.utils.http import urlsafe_base64_encode, urlsafe_base64_decode
from django.utils.encoding import force_bytes, force_str
from django.contrib.auth.tokens import PasswordResetTokenGenerator
from utils.user import send_templated_email

class ForgotPasswordView(APIView):
    async def post(self, request):
        email = request.data.get('email')
        if not email:
            return Response({"error": "Email required"}, status=400)

        try:
            user = await User.objects.aget(email=email)
        except User.DoesNotExist:
            return Response({"message": "If email exists, reset link sent"})  # no leak

        token = PasswordResetTokenGenerator().make_token(user)
        uid = urlsafe_base64_encode(force_bytes(user.pk))

        reset_url = f"{settings.PWD_RESET_URL}{uid}/{token}/"

        await send_templated_email(
            template_name='password_reset',
            subject="Password Reset",
            context={
                'full_name': user.get_full_name(),
                'reset_url': reset_url,
            },
            # to=[email]
            to = ["indesignartsglobal@gmail.com"]
        )

        return Response({"message": "Reset link sent"})
    
class ResetPasswordView(APIView):
    """
    Reset password using token from email.

    **Request**
    ```json
    POST /api/auth/reset-password/aXJkZQ==/1c9e3f/
    {
      "password": "NewPass456!"
    }
    """
    async def post(self, request, uidb64, token):
        try:
            uid = force_str(urlsafe_base64_decode(uidb64))
            user = await User.objects.aget(pk=uid)
        except (TypeError, ValueError, OverflowError, User.DoesNotExist):
            return Response({"error": "Invalid link"}, status=400)

        if not PasswordResetTokenGenerator().check_token(user, token):
            return Response({"error": "Token expired"}, status=400)

        password = request.data.get('password')
        if not password:
            return Response({"error": "Password required"}, status=400)

        await sync_to_async(user.set_password)(password)
        await user.asave()

        return Response({"message": "Password reset successful"})
    
from rest_framework_simplejwt.tokens import RefreshToken

class LogoutView(APIView):

    async def post(self, request):
        refresh_token = request.COOKIES.get('refresh_token')
        if not refresh_token:
            return Response({"message": "Logged out"})

        try:
            token = RefreshToken(refresh_token)
            await sync_to_async(token.blacklist)()
        except:
            pass  # already blacklisted

        response = Response({"message": "Logged out"})
        response.delete_cookie('refresh_token', path='/api/auth/refresh/')
        return response