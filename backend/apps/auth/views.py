from rest_framework import status, generics
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework_simplejwt.tokens import RefreshToken
from django.contrib.auth import login
from .models import User, APIKey, EmailVerification, UserPreferences, UserFeedback, SupportRequest
from .serializers import (
    UserRegistrationSerializer,
    UserLoginSerializer,
    UserSerializer,
    APIKeySerializer,
    APIKeyListSerializer,
    VerifyEmailSerializer,
    ResendOTPSerializer,
    UserPreferencesSerializer,
    UserFeedbackSerializer,
    SupportRequestSerializer
)
from django.utils import timezone
from apps.core.views import BaseViewSet
from apps.organizations.models import Organization, Membership
from apps.background_jobs.models import OutboxEvent
from apps.core.logging_config import get_logger
from django.db import transaction
from .services import AuthenticationService

logger = get_logger(__name__)

class UserRegistrationView(generics.CreateAPIView):
    """User registration endpoint"""
    queryset = User.objects.all()
    serializer_class = UserRegistrationSerializer
    permission_classes = [AllowAny]

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        
        # Check if user already exists but is not verified
        email = request.data.get('email')
        try:
            existing_user = User.objects.get(email=email)
            if not existing_user.is_email_verified:
                # Delete unverified user to allow re-registration
                existing_user.delete()
        except User.DoesNotExist:
            pass
            
        serializer.is_valid(raise_exception=True)
        
        try:
            with transaction.atomic():
                user = serializer.save()
                
                # Create default organization for new user
                org_name = f"{user.name}'s Organization"
                org_slug = f"{user.username}-org"
                
                # Ensure unique slug
                counter = 1
                original_slug = org_slug
                while Organization.objects.filter(slug=org_slug).exists():
                    org_slug = f"{original_slug}-{counter}"
                    counter += 1
                
                organization = Organization.objects.create(
                    name=org_name,
                    slug=org_slug,
                    status='active',
                    plan_tier='trial'
                )
                
                # Create owner membership
                Membership.objects.create(
                    user=user,
                    organization=organization,
                    role='owner'
                )

                # Use AuthenticationService to generate OTP and send email
                auth_service = AuthenticationService()
                try:
                    auth_service.send_verification_and_create_record(
                        email=user.email,
                        user=user,
                        email_type='registration'
                    )
                except Exception as e:
                    # Reraise exception to trigger transaction rollback
                    raise Exception(f"Failed to send verification email: {str(e)}")
                
                return Response({
                    'message': 'Registration successful. Please verify your email.',
                    'user': UserSerializer(user).data,
                    'email': user.email
                }, status=status.HTTP_201_CREATED)
                
        except Exception as e:
            # Transaction rolled back automatically
            return Response(
                {'error': str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class VerifyEmailView(generics.GenericAPIView):
    """Verify email with OTP"""
    serializer_class = VerifyEmailSerializer
    permission_classes = [AllowAny]

    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        email = serializer.validated_data['email']
        otp = serializer.validated_data['otp']
        
        # Verify OTP
        try:
            verification = EmailVerification.objects.filter(
                email=email,
                otp=otp,
                expires_at__gt=timezone.now()
            ).latest('created_at')
        except EmailVerification.DoesNotExist:
            return Response(
                {'error': 'Invalid or expired verification code'},
                status=status.HTTP_400_BAD_REQUEST
            )
            
        # Activate user
        try:
            user = User.objects.get(email=email)
            user.is_email_verified = True
            user.save()
            
            # Login user and generate tokens
            login(request, user)
            
            # Get user's primary organization (first one they own)
            primary_org = Organization.objects.filter(
                memberships__user=user,
                memberships__role='owner'
            ).first()
            
            # Generate JWT tokens
            refresh = RefreshToken.for_user(user)
            access_token = refresh.access_token
            
            # Add organization context to token
            if primary_org:
                access_token['org_id'] = str(primary_org.id)
                access_token['org_name'] = primary_org.name
            
            response_data = {
                'message': 'Email verified successfully',
                'user': UserSerializer(user).data,
                'tokens': {
                    'access': str(access_token),
                    'refresh': str(refresh),
                }
            }
            
            if primary_org:
                response_data['organization'] = {
                    'id': str(primary_org.id),
                    'name': primary_org.name,
                    'slug': primary_org.slug,
                    'plan_tier': primary_org.plan_tier
                }
            
            return Response(response_data)
            
        except User.DoesNotExist:
            return Response(
                {'error': 'User not found'},
                status=status.HTTP_404_NOT_FOUND
            )


class ResendOTPView(generics.GenericAPIView):
    """Resend verification OTP"""
    serializer_class = ResendOTPSerializer
    permission_classes = [AllowAny]

    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        email = serializer.validated_data['email']
        
        try:
            user = User.objects.get(email=email)
            if user.is_email_verified:
                return Response(
                    {'message': 'Email already verified'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            # Use AuthenticationService to generate OTP and send email
            auth_service = AuthenticationService()
            try:
                auth_service.send_verification_and_create_record(
                    email=email,
                    user=user,
                    email_type='otp_resend'
                )
            except Exception as e:
                return Response(
                    {'error': 'Failed to send verification email'},
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR
                )

            
            return Response({'message': 'Verification code sent'})
            
        except User.DoesNotExist:
            # Don't reveal user existence
            return Response({'message': 'Verification code sent'})


class UserLoginView(generics.GenericAPIView):
    """User login endpoint"""
    serializer_class = UserLoginSerializer
    permission_classes = [AllowAny]

    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        user = serializer.validated_data['user']
        
        # Check email verification
        if not getattr(user, 'is_email_verified', False):
            # Use AuthenticationService to generate OTP and send email
            auth_service = AuthenticationService()
            try:
                auth_service.send_verification_and_create_record(
                    email=user.email,
                    user=user,
                    email_type='unverified_login'
                )
            except Exception:
                # Log error but don't fail login - error already logged in service
                pass

            
            return Response(
                {
                    'error': 'Email not verified. A verification code has been sent to your email.',
                    'code': 'email_not_verified',
                    'email': user.email
                },
                status=status.HTTP_403_FORBIDDEN
            )

        login(request, user)
        
        # Get user's primary organization (first one they own)
        primary_org = Organization.objects.filter(
            memberships__user=user,
            memberships__role='owner'
        ).first()
        
        # Generate JWT tokens
        refresh = RefreshToken.for_user(user)
        access_token = refresh.access_token
        
        # Add organization context to token
        if primary_org:
            access_token['org_id'] = str(primary_org.id)
            access_token['org_name'] = primary_org.name
        
        response_data = {
            'user': UserSerializer(user).data,
            'tokens': {
                'access': str(access_token),
                'refresh': str(refresh),
            }
        }
        
        if primary_org:
            response_data['organization'] = {
                'id': str(primary_org.id),
                'name': primary_org.name,
                'slug': primary_org.slug,
                'plan_tier': primary_org.plan_tier
            }
        
        return Response(response_data)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def user_profile(request):
    """Get current user profile with memberships"""
    user = request.user

    # Get user's organizations
    memberships = Membership.objects.filter(user=user).select_related('organization')
    organizations = []

    for membership in memberships:
        organizations.append({
            'id': str(membership.organization.id),
            'name': membership.organization.name,
            'slug': membership.organization.slug,
            'plan_tier': membership.organization.plan_tier,
            'role': membership.role,
            'joined_at': membership.created_at
        })

    user_data = UserSerializer(user).data
    user_data['organizations'] = organizations

    return Response(user_data)


@api_view(['PATCH'])
@permission_classes([IsAuthenticated])
def update_profile(request):
    """
    PATCH /v1/auth/profile/update/ — Update user profile information

    Allows updating: first_name, last_name
    """
    logger.info(f"Profile update request from user: {request.user.id}")

    try:
        user = request.user

        # Update allowed fields only
        first_name = request.data.get('first_name')
        last_name = request.data.get('last_name')

        if first_name is not None:
            user.first_name = first_name.strip()[:150]  # Max length validation

        if last_name is not None:
            user.last_name = last_name.strip()[:150]

        user.save(update_fields=['first_name', 'last_name', 'updated_at'])

        logger.info(f"Profile updated successfully for user: {user.id}")
        return Response({
            'message': 'Profile updated successfully',
            'user': UserSerializer(user).data
        })

    except Exception as e:
        logger.error(f"Error updating profile: {str(e)}", exc_info=True)
        return Response(
            {'error': 'Failed to update profile'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def change_password(request):
    """
    POST /v1/auth/password/change/ — Change user password

    Requires: current_password, new_password, confirm_password
    """
    logger.info(f"Password change request from user: {request.user.id}")

    try:
        user = request.user

        # Validate required fields
        current_password = request.data.get('current_password')
        new_password = request.data.get('new_password')
        confirm_password = request.data.get('confirm_password')

        if not all([current_password, new_password, confirm_password]):
            return Response(
                {'error': 'All fields are required: current_password, new_password, confirm_password'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Verify current password
        if not user.check_password(current_password):
            return Response(
                {'error': 'Current password is incorrect'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Validate new passwords match
        if new_password != confirm_password:
            return Response(
                {'error': 'New passwords do not match'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Validate new password strength (minimum 8 characters)
        if len(new_password) < 8:
            return Response(
                {'error': 'New password must be at least 8 characters long'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Ensure new password is different from current
        if current_password == new_password:
            return Response(
                {'error': 'New password must be different from current password'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Update password
        user.set_password(new_password)
        user.save(update_fields=['password', 'updated_at'])

        logger.info(f"Password changed successfully for user: {user.id}")
        return Response({
            'message': 'Password changed successfully. Please log in with your new password.'
        })

    except Exception as e:
        logger.error(f"Error changing password: {str(e)}", exc_info=True)
        return Response(
            {'error': 'Failed to change password'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def update_email(request):
    """
    POST /v1/auth/email/update/ — Request email address change

    Requires: new_email, password
    Sends verification to new email address
    """
    logger.info(f"Email update request from user: {request.user.id}")

    try:
        user = request.user

        # Validate required fields
        new_email = request.data.get('new_email', '').strip().lower()
        password = request.data.get('password')

        if not new_email or not password:
            return Response(
                {'error': 'new_email and password are required'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Verify password
        if not user.check_password(password):
            return Response(
                {'error': 'Password is incorrect'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Check if email is already in use
        if User.objects.filter(email=new_email).exclude(id=user.id).exists():
            return Response(
                {'error': 'This email address is already in use'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Validate email format
        if '@' not in new_email or '.' not in new_email.split('@')[1]:
            return Response(
                {'error': 'Invalid email format'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Send verification email to new address
        auth_service = AuthenticationService()
        try:
            auth_service.send_verification_and_create_record(
                email=new_email,
                user=user,
                email_type='email_change'
            )
        except Exception as e:
            logger.error(f"Failed to send verification email: {str(e)}", exc_info=True)
            return Response(
                {'error': 'Failed to send verification email'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

        logger.info(f"Email verification sent to {new_email} for user: {user.id}")
        return Response({
            'message': f'Verification code sent to {new_email}. Please verify to complete email change.',
            'new_email': new_email
        })

    except Exception as e:
        logger.error(f"Error updating email: {str(e)}", exc_info=True)
        return Response(
            {'error': 'Failed to update email'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def verify_email_change(request):
    """
    POST /v1/auth/email/verify-change/ — Verify and complete email change

    Requires: new_email, otp_code
    """
    logger.info(f"Email change verification from user: {request.user.id}")

    try:
        user = request.user
        new_email = request.data.get('new_email', '').strip().lower()
        otp_code = request.data.get('otp_code', '').strip()

        if not new_email or not otp_code:
            return Response(
                {'error': 'new_email and otp_code are required'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Verify OTP
        auth_service = AuthenticationService()
        is_valid = auth_service.verify_email_with_otp(new_email, otp_code)

        if not is_valid:
            return Response(
                {'error': 'Invalid or expired verification code'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Check email is still available
        if User.objects.filter(email=new_email).exclude(id=user.id).exists():
            return Response(
                {'error': 'This email address is no longer available'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Update email
        user.email = new_email
        user.username = new_email  # Keep username in sync with email
        user.save(update_fields=['email', 'username', 'updated_at'])

        logger.info(f"Email changed successfully for user: {user.id} to {new_email}")
        return Response({
            'message': 'Email address updated successfully',
            'user': UserSerializer(user).data
        })

    except Exception as e:
        logger.error(f"Error verifying email change: {str(e)}", exc_info=True)
        return Response(
            {'error': 'Failed to verify email change'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['DELETE'])
@permission_classes([IsAuthenticated])
def delete_account(request):
    """
    DELETE /v1/auth/account/delete/ — Permanently delete user account

    Requires: password, confirmation
    WARNING: This action is irreversible
    """
    logger.info(f"Account deletion request from user: {request.user.id}")

    try:
        user = request.user

        # Validate required fields
        password = request.data.get('password')
        confirmation = request.data.get('confirmation')

        if not password:
            return Response(
                {'error': 'Password is required to delete account'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Verify password
        if not user.check_password(password):
            return Response(
                {'error': 'Password is incorrect'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Require explicit confirmation
        if confirmation != 'DELETE MY ACCOUNT':
            return Response(
                {'error': 'Please type "DELETE MY ACCOUNT" in the confirmation field'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Check if user is the sole owner of any organizations
        owned_orgs = Membership.objects.filter(user=user, role='owner').select_related('organization')
        for membership in owned_orgs:
            org = membership.organization
            owner_count = Membership.objects.filter(organization=org, role='owner').count()
            if owner_count == 1:
                # User is the only owner - need to handle organization deletion or transfer
                other_members = Membership.objects.filter(organization=org).exclude(user=user).count()
                if other_members > 0:
                    return Response(
                        {
                            'error': f'You are the sole owner of organization "{org.name}". Please transfer ownership or delete the organization first.'
                        },
                        status=status.HTTP_400_BAD_REQUEST
                    )

        user_id = str(user.id)
        user_email = user.email

        # Delete user (cascade will handle related data)
        with transaction.atomic():
            user.delete()

        logger.info(f"Account deleted successfully for user: {user_id} ({user_email})")
        return Response({
            'message': 'Account deleted successfully'
        }, status=status.HTTP_200_OK)

    except Exception as e:
        logger.error(f"Error deleting account: {str(e)}", exc_info=True)
        return Response(
            {'error': 'Failed to delete account'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['GET', 'PUT', 'PATCH'])
@permission_classes([IsAuthenticated])
def user_preferences(request):
    """
    GET /v1/auth/preferences/ — Get user preferences
    PUT/PATCH /v1/auth/preferences/ — Update user preferences
    """
    logger.info(f"User preferences request ({request.method}) from user: {request.user.id}")

    try:
        # Get or create user preferences
        preferences, created = UserPreferences.objects.get_or_create(user=request.user)

        if request.method == 'GET':
            serializer = UserPreferencesSerializer(preferences)
            return Response(serializer.data)

        elif request.method in ['PUT', 'PATCH']:
            # Partial update for PATCH, full update for PUT
            partial = request.method == 'PATCH'
            serializer = UserPreferencesSerializer(
                preferences,
                data=request.data,
                partial=partial,
                context={'request': request}
            )

            if not serializer.is_valid():
                return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

            serializer.save()

            logger.info(f"Preferences updated successfully for user: {request.user.id}")
            return Response({
                'message': 'Preferences updated successfully',
                'preferences': serializer.data
            })

    except Exception as e:
        logger.error(f"Error handling preferences: {str(e)}", exc_info=True)
        return Response(
            {'error': 'Failed to process preferences'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def submit_feedback(request):
    """
    POST /v1/auth/feedback/ — Submit user feedback
    """
    logger.info(f"Feedback submission from user: {request.user.id}")

    try:
        serializer = UserFeedbackSerializer(data=request.data, context={'request': request})

        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        feedback = serializer.save()

        logger.info(f"Feedback submitted successfully by user: {request.user.id}, rating: {feedback.rating}")

        return Response({
            'message': 'Thank you for your feedback! We appreciate your input.',
            'feedback': serializer.data
        }, status=status.HTTP_201_CREATED)

    except Exception as e:
        logger.error(f"Error submitting feedback: {str(e)}", exc_info=True)
        return Response(
            {'error': 'Failed to submit feedback. Please try again later.'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def submit_support_request(request):
    """
    POST /v1/auth/support/ — Submit a support request
    """
    logger.info(f"Support request submission from user: {request.user.id}")

    try:
        serializer = SupportRequestSerializer(data=request.data, context={'request': request})

        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        support_request = serializer.save()

        logger.info(f"Support request submitted successfully by user: {request.user.id}, category: {support_request.category}")

        return Response({
            'message': 'Your request has been submitted. We will get back to you within 24 hours.',
            'request': serializer.data
        }, status=status.HTTP_201_CREATED)

    except Exception as e:
        logger.error(f"Error submitting support request: {str(e)}", exc_info=True)
        return Response(
            {'error': 'Failed to submit support request. Please try again later.'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


class APIKeyViewSet(BaseViewSet):
    """API Key management"""
    queryset = APIKey.objects.all()
    permission_classes = [IsAuthenticated]

    def get_serializer_class(self):
        if self.action == 'create':
            return APIKeySerializer
        return APIKeyListSerializer

    def get_queryset(self):
        """Filter API keys by organization"""
        queryset = super().get_queryset()
        request = self.request
        
        if hasattr(request, 'org_id') and request.org_id:
            return queryset.filter(org_id=request.org_id)
        
        return queryset.none()

    def create(self, request, *args, **kwargs):
        """Create new API key"""
        # Validate scopes
        scopes = request.data.get('scopes', [])
        valid_scopes = [
            'indexing:write', 'chat:read', 'chat:write', 
            'sites:write', 'sites:read', 'org:read'
        ]
        
        for scope in scopes:
            if scope not in valid_scopes:
                return Response(
                    {'error': f'Invalid scope: {scope}. Valid scopes: {valid_scopes}'}, 
                    status=status.HTTP_400_BAD_REQUEST
                )
        
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        api_key = serializer.save()
        
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    def destroy(self, request, *args, **kwargs):
        """Revoke API key"""
        instance = self.get_object()
        instance.is_active = False
        instance.save()

        return Response(status=status.HTTP_204_NO_CONTENT)

    def rotate(self, request, pk=None):
        """
        POST /v1/auth/api-keys/{id}/rotate/ — Rotate API key (generate new token)

        This creates a new API key with the same settings and revokes the old one.
        """
        logger.info(f"API key rotation request from user: {request.user.id}")

        try:
            old_key = self.get_object()

            # Create new API key with same settings
            new_key = APIKey.objects.create(
                org_id=old_key.org_id,
                name=old_key.name,
                scopes=old_key.scopes,
                expires_at=old_key.expires_at
            )

            # Revoke old key
            old_key.is_active = False
            old_key.save()

            logger.info(f"API key rotated successfully. Old: {old_key.id}, New: {new_key.id}")
            return Response(APIKeySerializer(new_key).data)

        except Exception as e:
            logger.error(f"Error rotating API key: {str(e)}", exc_info=True)
            return Response(
                {'error': 'Failed to rotate API key'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def send_test_email(request):
    """
    POST /v1/auth/test-email/ — Trigger a test email notification
    """
    logger.info(f"Test email request from user: {request.user.id}")

    try:
        user = request.user
        
        # Check if email notifications are enabled
        try:
            prefs = UserPreferences.objects.get(user=user)
            if not prefs.email_notifications:
                return Response(
                    {'error': 'Email notifications are disabled in your settings. Please enable them first.'},
                    status=status.HTTP_400_BAD_REQUEST
                )
        except UserPreferences.DoesNotExist:
            # Default is true, so proceed if not found
            pass

        # Create outbox event for sending email
        OutboxEvent.objects.create(
            event_type='send_email',
            payload={
                'to': [user.email],
                'subject': 'Test Notification from Webbotify',
                'body': f'Hello {user.first_name},\n\nThis is a test notification to confirm that your email settings are configured correctly.\n\nBest regards,\nThe Webbotify Team',
                'html_body': f'''
                <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
                    <h2>Test Notification</h2>
                    <p>Hello {user.first_name},</p>
                    <p>This is a test notification to confirm that your email settings are configured correctly.</p>
                    <div style="background-color: #f3f4f6; padding: 15px; border-radius: 5px; margin: 20px 0;">
                        <p style="margin: 0; color: #4b5563;">Status: <strong>Active</strong></p>
                    </div>
                    <p>Best regards,<br>The Webbotify Team</p>
                </div>
                '''
            }
        )

        logger.info(f"Test email queued for user: {user.id} ({user.email})")
        return Response({
            'message': 'Test email queued successfully. You should receive it shortly.'
        })

    except Exception as e:
        logger.error(f"Error sending test email: {str(e)}", exc_info=True)
        return Response(
            {'error': 'Failed to queue test email'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )

