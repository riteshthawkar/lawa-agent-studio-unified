from rest_framework import serializers
from .models import Organization, Membership
from apps.auth.serializers import UserSerializer


class OrganizationSerializer(serializers.ModelSerializer):
    """Serializer for Organization model"""
    
    class Meta:
        model = Organization
        fields = ('id', 'name', 'slug', 'status', 'plan_tier', 'created_at')
        read_only_fields = ('id', 'created_at')


class OrganizationCreateSerializer(serializers.ModelSerializer):
    """Serializer for creating organizations"""
    
    class Meta:
        model = Organization
        fields = ('name', 'slug')

    def validate_slug(self, value):
        """Validate slug uniqueness"""
        if Organization.objects.filter(slug=value).exists():
            raise serializers.ValidationError("Organization with this slug already exists")
        return value


class MembershipSerializer(serializers.ModelSerializer):
    """Serializer for Membership model"""
    user = UserSerializer(read_only=True)
    user_id = serializers.UUIDField(write_only=True)
    
    class Meta:
        model = Membership
        fields = ('id', 'user', 'user_id', 'role', 'created_at')
        read_only_fields = ('id', 'created_at')

    def create(self, validated_data):
        """Create membership with user lookup"""
        user_id = validated_data.pop('user_id')
        try:
            from apps.auth.models import User
            user = User.objects.get(id=user_id)
            validated_data['user'] = user
        except User.DoesNotExist:
            raise serializers.ValidationError("User not found")
        
        return super().create(validated_data)


class OrganizationDetailSerializer(serializers.ModelSerializer):
    """Serializer for organization details with memberships"""
    memberships = MembershipSerializer(many=True, read_only=True)
    
    class Meta:
        model = Organization
        fields = ('id', 'name', 'slug', 'status', 'plan_tier', 'created_at', 'memberships')
        read_only_fields = ('id', 'created_at', 'memberships')
