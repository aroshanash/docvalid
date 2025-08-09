from rest_framework import generics, permissions, views, status
from .serializers import RegisterSerializer, UserSerializer
from django.contrib.auth import get_user_model
from rest_framework.response import Response
from django.shortcuts import get_object_or_404
from rest_framework_simplejwt.tokens import RefreshToken

User = get_user_model()

class RegisterView(generics.CreateAPIView):
    queryset = User.objects.all()
    permission_classes = [permissions.AllowAny]
    serializer_class = RegisterSerializer

class CurrentUserView(generics.RetrieveAPIView):
    serializer_class = UserSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_object(self):
        return self.request.user
    

class UserListView(generics.ListAPIView):
    """
    Admin-only: list all users to enable user-switching in the frontend.
    """
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = UserSerializer

    def get_queryset(self):
        user = self.request.user
        if not getattr(user, 'role', None) or not user.is_admin():
            # Non-admins should get empty list (or you could return 403)
            return User.objects.none()
        return User.objects.all().order_by('username')

class ImpersonateView(views.APIView):
    """
    Admin-only: create JWT tokens for the target user so admin can switch to that user.
    Returns 'access' and 'refresh' tokens.
    """
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, *args, **kwargs):
        if not request.user.is_admin():
            return Response({'detail': 'Not permitted'}, status=status.HTTP_403_FORBIDDEN)

        user_id = request.data.get('user_id')
        if not user_id:
            return Response({'detail': 'user_id is required'}, status=status.HTTP_400_BAD_REQUEST)

        target_user = get_object_or_404(User, pk=user_id)
        refresh = RefreshToken.for_user(target_user)
        return Response({'access': str(refresh.access_token), 'refresh': str(refresh)})