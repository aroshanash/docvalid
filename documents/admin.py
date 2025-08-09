from django.contrib import admin
from .models import TradeDocument, DocumentFile, ValidationRule, ValidationResult, Comment, CurrencyRate, AuditLog, UserPreference

admin.site.register([TradeDocument, DocumentFile, ValidationRule, ValidationResult, Comment, CurrencyRate, AuditLog, UserPreference])