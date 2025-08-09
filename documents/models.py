from django.db import models
from django.conf import settings
from django.utils import timezone

User = settings.AUTH_USER_MODEL

class TradeDocument(models.Model):
    TYPE_INVOICE = 'invoice'
    TYPE_PACKING = 'packing_list'
    TYPE_BOL = 'bol_awb'
    TYPE_DELIVERY = 'delivery_order'
    DOC_TYPE_CHOICES = [
        (TYPE_INVOICE, 'Invoice'),
        (TYPE_PACKING, 'Packing List'),
        (TYPE_BOL, 'BOL/AWB'),
        (TYPE_DELIVERY, 'Delivery Order'),
    ]

    STATUS_UPLOADED = 'uploaded'
    STATUS_PENDING = 'pending'
    STATUS_APPROVED = 'approved'
    STATUS_REJECTED = 'rejected'
    STATUS_CHOICES = [
        (STATUS_UPLOADED, 'Uploaded'),
        (STATUS_PENDING, 'Pending'),
        (STATUS_APPROVED, 'Approved'),
        (STATUS_REJECTED, 'Rejected'),
    ]

    doc_type = models.CharField(max_length=50, choices=DOC_TYPE_CHOICES)
    uploader = models.ForeignKey(User, on_delete=models.CASCADE, related_name='uploaded_documents')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_UPLOADED)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)
    assigned_reviewer = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='assigned_documents')
    last_validation = models.JSONField(null=True, blank=True)
    # metadata holds any textual numeric metadata (e.g. value, currency) submitted along with files
    metadata = models.JSONField(default=dict, blank=True)

    def __str__(self):
        return f"{self.get_doc_type_display()} ({self.id}) by {self.uploader.username}"

class DocumentFile(models.Model):
    """
    Represents a file uploaded for a specific required subfield of a TradeDocument.
    e.g. field_name="hs_code", file=<File>, uploaded_at=...
    """
    document = models.ForeignKey(TradeDocument, on_delete=models.CASCADE, related_name='files')
    field_name = models.CharField(max_length=128)  # e.g. 'hs_code', 'goods_description'
    file = models.FileField(upload_to='documents/%Y/%m/%d/')
    uploaded_at = models.DateTimeField(default=timezone.now)

    class Meta:
        unique_together = ('document', 'field_name')

    def __str__(self):
        return f"File for {self.field_name} of doc {self.document_id}"

class ValidationRule(models.Model):
    doc_type = models.CharField(max_length=50, choices=TradeDocument.DOC_TYPE_CHOICES)
    field_name = models.CharField(max_length=128)
    required = models.BooleanField(default=True)
    description = models.TextField(blank=True)

    def __str__(self):
        return f"{self.doc_type}: {self.field_name} (required={self.required})"

class ValidationResult(models.Model):
    document = models.ForeignKey(TradeDocument, on_delete=models.CASCADE, related_name='validation_results')
    # version field removed; we store which files exist in result
    result = models.JSONField(default=dict)
    run_at = models.DateTimeField(default=timezone.now)
    run_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)

class Comment(models.Model):
    document = models.ForeignKey(TradeDocument, on_delete=models.CASCADE, related_name='comments')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    text = models.TextField()
    created_at = models.DateTimeField(default=timezone.now)

class CurrencyRate(models.Model):
    currency = models.CharField(max_length=10, unique=True)
    rate_to_aed = models.DecimalField(max_digits=20, decimal_places=6)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"1 {self.currency} = {self.rate_to_aed} AED"

class AuditLog(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    action = models.CharField(max_length=255)
    details = models.JSONField(null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now)

class UserPreference(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='preference')
    dark_mode = models.BooleanField(default=False)
    email_notifications = models.BooleanField(default=True)

class UserActivityLog(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    action = models.CharField(max_length=255)
    timestamp = models.DateTimeField(default=timezone.now)



# backend/documents/models.py (snippet - DocumentFile model replaceme

# ... ensure TradeDocument, ValidationResult, AuditLog models stay unchanged above this model ...

class DocumentFile(models.Model):
    """
    Represents a file uploaded for a specific sub-field of a TradeDocument.
    extraction_status: pending/running/done/failed
    extracted_text: full text extracted by OCR/text-extraction
    """
    STATUS_PENDING = 'pending'
    STATUS_RUNNING = 'running'
    STATUS_DONE = 'done'
    STATUS_FAILED = 'failed'
    STATUS_CHOICES = [
        (STATUS_PENDING, 'Pending'),
        (STATUS_RUNNING, 'Running'),
        (STATUS_DONE, 'Done'),
        (STATUS_FAILED, 'Failed'),
    ]

    document = models.ForeignKey('TradeDocument', on_delete=models.CASCADE, related_name='files')
    field_name = models.CharField(max_length=128)  # e.g. 'hs_code', 'goods_description'
    file = models.FileField(upload_to='documents/%Y/%m/%d/')
    uploaded_at = models.DateTimeField(default=timezone.now)

    extraction_status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING)
    extracted_text = models.TextField(null=True, blank=True)

    class Meta:
        unique_together = ('document', 'field_name')

    def __str__(self):
        return f"File for {self.field_name} of doc {self.document_id}"

    def get_text_snippet(self, length=400):
        if not self.extracted_text:
            return ''
        txt = self.extracted_text.strip().replace('\n', ' ')
        return txt[:length] + ('...' if len(txt) > length else '')
