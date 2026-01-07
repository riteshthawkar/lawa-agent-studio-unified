from rest_framework import serializers


class BaseSerializer(serializers.ModelSerializer):
    """Base serializer with common functionality"""
    
    def create(self, validated_data):
        # Add organization context if available
        request = self.context.get('request')
        if request and hasattr(request, 'org_id'):
            validated_data['org_id'] = request.org_id
        return super().create(validated_data)
