from rest_framework import serializers
from django.contrib.auth import authenticate
from django.contrib.auth.password_validation import validate_password
from .models import User, APIKey, UserPreferences, UserFeedback, SupportRequest
import secrets
import hashlib


class UserRegistrationSerializer(serializers.ModelSerializer):
    """Serializer for user registration"""
    password = serializers.CharField(write_only=True, validators=[validate_password])
    password_confirm = serializers.CharField(write_only=True)

    class Meta:
        model = User
        fields = ('email', 'username', 'name', 'password', 'password_confirm')
        extra_kwargs = {
            'email': {'required': True},
            'username': {'required': True},
            'name': {'required': True},
        }

    def validate(self, attrs):
        if attrs['password'] != attrs['password_confirm']:
            raise serializers.ValidationError("Passwords don't match")
        return attrs

    def create(self, validated_data):
        validated_data.pop('password_confirm')
        user = User.objects.create_user(**validated_data)
        return user


class UserLoginSerializer(serializers.Serializer):
    """Serializer for user login"""
    email = serializers.EmailField()
    password = serializers.CharField()

    def validate(self, attrs):
        email = attrs.get('email')
        password = attrs.get('password')

        if email and password:
            user = authenticate(username=email, password=password)
            if not user:
                raise serializers.ValidationError('Invalid credentials')
            if not user.is_active:
                raise serializers.ValidationError('User account is disabled')
            attrs['user'] = user
        else:
            raise serializers.ValidationError('Must include email and password')

        return attrs


class UserSerializer(serializers.ModelSerializer):
    """Serializer for user profile"""
    
    class Meta:
        model = User
        fields = ('id', 'email', 'username', 'name', 'status', 'is_staff', 'is_superuser', 'created_at')
        read_only_fields = ('id', 'is_staff', 'is_superuser', 'created_at')


class APIKeySerializer(serializers.ModelSerializer):
    """Serializer for API key management"""
    token = serializers.CharField(read_only=True, help_text="Plaintext token (only shown on creation)")
    
    class Meta:
        model = APIKey
        fields = ('id', 'name', 'scopes', 'is_active', 'created_at', 'last_used_at', 'token')
        read_only_fields = ('id', 'created_at', 'last_used_at', 'token')

    def create(self, validated_data):
        # Generate a secure random token
        token = secrets.token_urlsafe(32)
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        
        # Add organization context
        request = self.context.get('request')
        if request and hasattr(request, 'org_id'):
            validated_data['org_id'] = request.org_id
        
        validated_data['token_hash'] = token_hash
        api_key = super().create(validated_data)
        
        # Store the plaintext token temporarily for response
        api_key.token = token
        return api_key


class APIKeyListSerializer(serializers.ModelSerializer):
    """Serializer for API key listing (without token)"""

    class Meta:
        model = APIKey
        fields = ('id', 'name', 'scopes', 'is_active', 'created_at', 'last_used_at')
        read_only_fields = ('id', 'created_at', 'last_used_at')


class VerifyEmailSerializer(serializers.Serializer):
    """Serializer for email verification"""
    email = serializers.EmailField()
    otp = serializers.CharField(max_length=6, min_length=6)


class ResendOTPSerializer(serializers.Serializer):
    """Serializer for resending OTP"""
    email = serializers.EmailField()


class UserPreferencesSerializer(serializers.ModelSerializer):
    """Serializer for user preferences and settings"""

    class Meta:
        model = UserPreferences
        fields = (
            'email_notifications',
            'push_notifications',
            'indexing_notifications',
            'chatbot_notifications',
            'weekly_digest',
            'theme',
            'language',
            'timezone',
            'enable_analytics',
            'enable_tooltips',
            'compact_mode',
            'onboarding_completed',
            'tour_completed',
        )

    def create(self, validated_data):
        # Get user from context
        user = self.context['request'].user
        validated_data['user'] = user
        return super().create(validated_data)

    def update(self, instance, validated_data):
        # Update all fields
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()
        return instance


class UserFeedbackSerializer(serializers.ModelSerializer):
    """Serializer for user feedback submission"""

    class Meta:
        model = UserFeedback
        fields = ('id', 'rating', 'comments', 'allow_contact', 'page_url', 'created_at', 'status')
        read_only_fields = ('id', 'created_at', 'status')

    def create(self, validated_data):
        # Get user and org from context
        request = self.context.get('request')
        validated_data['user'] = request.user

        # Add organization context if available
        if hasattr(request, 'org_id'):
            validated_data['org_id'] = request.org_id

        # Add metadata from request
        if request:
            validated_data['user_agent'] = request.META.get('HTTP_USER_AGENT', '')[:500]

        return super().create(validated_data)


class SupportRequestSerializer(serializers.ModelSerializer):
    """Serializer for support request submission"""

    class Meta:
        model = SupportRequest
        fields = ('id', 'category', 'subject', 'description', 'page_url', 'created_at', 'status')
        read_only_fields = ('id', 'created_at', 'status')

    def create(self, validated_data):
        # Get user and org from context
        request = self.context.get('request')
        validated_data['user'] = request.user

        # Add organization context if available
        if hasattr(request, 'org_id'):
            validated_data['org_id'] = request.org_id

        # Add metadata from request
        if request:
            validated_data['user_agent'] = request.META.get('HTTP_USER_AGENT', '')[:500]

        return super().create(validated_data)
