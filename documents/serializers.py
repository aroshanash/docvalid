from rest_framework import serializers
from .models import TradeDocument, DocumentFile, ValidationRule, ValidationResult, Comment, CurrencyRate, AuditLog, UserPreference
from django.contrib.auth import get_user_model
User = get_user_model()

class DocumentFileSerializer(serializers.ModelSerializer):
    file_url = serializers.SerializerMethodField()

    class Meta:
        model = DocumentFile
        fields = ('id', 'field_name', 'file', 'file_url', 'uploaded_at')
        read_only_fields = ('id','file_url','uploaded_at')

    def get_file_url(self, obj):
        request = self.context.get('request')
        if obj.file:
            return request.build_absolute_uri(obj.file.url) if request else obj.file.url
        return None

class TradeDocumentListSerializer(serializers.ModelSerializer):
    uploader = serializers.StringRelatedField()
    files = DocumentFileSerializer(many=True, read_only=True)

    class Meta:
        model = TradeDocument
        fields = ('id','doc_type','uploader','status','created_at','updated_at','assigned_reviewer','files')

class TradeDocumentDetailSerializer(serializers.ModelSerializer):
    uploader = serializers.StringRelatedField()
    files = DocumentFileSerializer(many=True, read_only=True)
    comments = serializers.SerializerMethodField()
    last_validation = serializers.JSONField(read_only=True)
    metadata = serializers.JSONField(read_only=True)

    class Meta:
        model = TradeDocument
        fields = ('id','doc_type','uploader','status','created_at','updated_at','assigned_reviewer','files','comments','last_validation','metadata')

    def get_comments(self, obj):
        return [{'user': c.user.username, 'text': c.text, 'created_at': c.created_at} for c in obj.comments.all().order_by('-created_at')]

class UploadDocumentSerializer(serializers.Serializer):
    """
    The upload endpoint will accept multiple file parts where each part name equals a required field name.
    Additionally, a 'metadata' JSON string can be sent for numeric/text metadata (e.g. value/currency).
    """
    doc_type = serializers.ChoiceField(choices=TradeDocument.DOC_TYPE_CHOICES)
    # files are read directly from request.FILES in view
    metadata = serializers.JSONField(required=False)

class CommentSerializer(serializers.ModelSerializer):
    user = serializers.StringRelatedField(read_only=True)
    class Meta:
        model = Comment
        fields = ('id','document','user','text','created_at')
        read_only_fields = ('user','created_at')

class ValidationRuleSerializer(serializers.ModelSerializer):
    class Meta:
        model = ValidationRule
        fields = '__all__'

class ValidationResultSerializer(serializers.ModelSerializer):
    class Meta:
        model = ValidationResult
        fields = '__all__'

class CurrencyRateSerializer(serializers.ModelSerializer):
    class Meta:
        model = CurrencyRate
        fields = '__all__'

class AuditLogSerializer(serializers.ModelSerializer):
    class Meta:
        model = AuditLog
        fields = '__all__'

class UserPreferenceSerializer(serializers.ModelSerializer):
    class Meta:
        model = UserPreference
        fields = ('dark_mode','email_notifications')