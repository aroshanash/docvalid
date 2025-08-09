import json
from rest_framework import generics, status, permissions, views
from rest_framework.response import Response
from .models import TradeDocument, DocumentFile, ValidationRule, ValidationResult, Comment, CurrencyRate, AuditLog, UserPreference
from .serializers import UploadDocumentSerializer, TradeDocumentListSerializer, TradeDocumentDetailSerializer, DocumentFileSerializer, CommentSerializer, ValidationRuleSerializer, ValidationResultSerializer, CurrencyRateSerializer, UserPreferenceSerializer
from django.shortcuts import get_object_or_404
from django.db import transaction
from django.contrib.auth import get_user_model
from decimal import Decimal
from .utils import get_rate_to_aed, calculate_duties_from_hs

User = get_user_model()

# Fields required as file uploads per doc type
REQUIRED_FIELDS = {
    TradeDocument.TYPE_INVOICE: ['hs_code','goods_description','unit_of_measure','quantity','weight','value','currency'],
    TradeDocument.TYPE_PACKING: ['hs_code','goods_description','unit_of_measure','quantity','gross_weight','net_weight','number_of_packages'],
    TradeDocument.TYPE_BOL: ['shipper','consignee','hs_code','weight','number_of_packages','bol_awb_number'],
    TradeDocument.TYPE_DELIVERY: ['consignee','container_number','port_of_discharge','currency','value','hs_code'],
}

class DocumentUploadView(views.APIView):
    permission_classes = [permissions.IsAuthenticated]

    @transaction.atomic
    def post(self, request, *args, **kwargs):
        # Validate doc_type and optional metadata JSON
        serializer = UploadDocumentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        doc_type = serializer.validated_data['doc_type']
        metadata = serializer.validated_data.get('metadata', {})

        required = REQUIRED_FIELDS.get(doc_type, [])
        missing_files = [f for f in required if f not in request.FILES]
        if missing_files:
            return Response({'detail': f"Missing required files for {doc_type}: {missing_files}"}, status=400)

        # Create TradeDocument record
        trade_doc = TradeDocument.objects.create(doc_type=doc_type, uploader=request.user, status=TradeDocument.STATUS_PENDING, metadata=metadata)

        # Save each required file using DocumentFile model
        created_files = []
        for field in required:
            uploaded_file = request.FILES.get(field)
            if not uploaded_file:
                continue  # already handled missing case above
            df = DocumentFile.objects.create(document=trade_doc, field_name=field, file=uploaded_file)
            created_files.append(df)

        # If delivery order, perform currency conversion/duties if metadata contains 'currency' and 'value'
        if doc_type == TradeDocument.TYPE_DELIVERY:
            currency = metadata.get('currency') or request.POST.get('currency')
            value = metadata.get('value') or request.POST.get('value')
            if currency and value:
                try:
                    rate = get_rate_to_aed(currency)
                    raw_value = Decimal(str(value))
                    value_in_aed = (raw_value * Decimal(str(rate))).quantize(Decimal('0.01'))
                    duties_res = calculate_duties_from_hs(metadata.get('hs_code', '') or request.POST.get('hs_code', ''), value_in_aed)
                    # store calculations inside metadata for quick access in UI
                    trade_doc.metadata = {**trade_doc.metadata, 'value_in_aed': str(value_in_aed), 'duties': str(duties_res['duties']), 'duty_percentage': str(duties_res['duty_percentage'])}
                    trade_doc.save(update_fields=['metadata'])
                except Exception as e:
                    # still allow upload but inform frontend
                    AuditLog.objects.create(user=request.user, action='currency_conversion_failed', details={'doc_id': trade_doc.id, 'error': str(e)})
                    return Response({'detail': f'Uploaded but currency/duties calculation failed: {str(e)}'}, status=201)

        AuditLog.objects.create(user=request.user, action='uploaded_document', details={'doc_id': trade_doc.id, 'doc_type': doc_type, 'files': [f.field_name for f in created_files]})
        return Response({'detail': 'Uploaded', 'document_id': trade_doc.id}, status=201)

class DocumentListView(generics.ListAPIView):
    serializer_class = TradeDocumentListSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        qs = TradeDocument.objects.all().order_by('-created_at')
        if user.is_admin():
            return qs
        if user.is_reviewer():
            return (qs.filter(assigned_reviewer=user) | qs.filter(status=TradeDocument.STATUS_PENDING, assigned_reviewer__isnull=True)).distinct()
        return qs.filter(uploader=user)

class DocumentDetailView(generics.RetrieveAPIView):
    serializer_class = TradeDocumentDetailSerializer
    permission_classes = [permissions.IsAuthenticated]
    queryset = TradeDocument.objects.all()

class ApproveRejectView(views.APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk):
        doc = get_object_or_404(TradeDocument, pk=pk)
        action = request.data.get('action')
        comment = request.data.get('comment', '')

        if not request.user.is_admin():
            if not request.user.is_reviewer():
                return Response({'detail': 'Not permitted'}, status=403)
            if doc.assigned_reviewer and doc.assigned_reviewer != request.user:
                return Response({'detail': 'Document not assigned to you'}, status=403)

        if action == 'approve':
            doc.status = TradeDocument.STATUS_APPROVED
        elif action == 'reject':
            doc.status = TradeDocument.STATUS_REJECTED
        else:
            return Response({'detail': 'Invalid action'}, status=400)
        doc.save()
        if comment:
            Comment.objects.create(document=doc, user=request.user, text=comment)
        AuditLog.objects.create(user=request.user, action=f'{action}_document', details={'doc_id': doc.id})
        return Response({'detail': f'Document {action}d'})

class RunValidationView(views.APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk):
        doc = get_object_or_404(TradeDocument, pk=pk)
        results = {}
        # 1) check file presence for required fields
        required = REQUIRED_FIELDS.get(doc.doc_type, [])
        existing_files = {f.field_name for f in doc.files.all()}
        missing_files = [f for f in required if f not in existing_files]
        results['missing_files'] = missing_files

        # 2) for delivery doc check metadata for value/currency to compute matching HS or other logic
        if doc.doc_type == TradeDocument.TYPE_DELIVERY:
            hs = doc.metadata.get('hs_code') or None
            if hs:
                same_hs_docs = TradeDocument.objects.filter(uploader=doc.uploader, files__field_name='hs_code', files__file__icontains=hs).distinct()
                results['matching_hs_count'] = same_hs_docs.count()
            # also surface computed duties if present
            if doc.metadata.get('duties'):
                results['duties'] = doc.metadata['duties']
                results['value_in_aed'] = doc.metadata.get('value_in_aed')

        ValidationResult.objects.create(document=doc, result=results, run_by=request.user)
        doc.last_validation = results
        doc.save(update_fields=['last_validation'])
        AuditLog.objects.create(user=request.user, action='run_validation', details={'doc_id': doc.id, 'results': results})
        return Response({'results': results})

class CommentCreateView(generics.CreateAPIView):
    serializer_class = CommentSerializer
    permission_classes = [permissions.IsAuthenticated]

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)
        AuditLog.objects.create(user=self.request.user, action='add_comment', details={'document': serializer.validated_data.get('document').id})

class CommentListView(generics.ListAPIView):
    serializer_class = CommentSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        doc_id = self.kwargs.get('pk')
        return Comment.objects.filter(document_id=doc_id).order_by('-created_at')

class CurrencyConvertView(views.APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        from_currency = request.query_params.get('from')
        amount = request.query_params.get('amount')
        if not from_currency or not amount:
            return Response({'detail': 'from and amount required'}, status=400)
        try:
            rate = get_rate_to_aed(from_currency)
            converted = (Decimal(str(amount)) * Decimal(str(rate))).quantize(Decimal('0.01'))
            return Response({'from': from_currency, 'amount': amount, 'to': 'AED', 'converted': str(converted)})
        except Exception as e:
            return Response({'detail': str(e)}, status=400)

class DocumentStatsView(views.APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        user = request.user
        qs = TradeDocument.objects.all()
        if not user.is_admin():
            if user.is_reviewer():
                qs = (qs.filter(assigned_reviewer=user) | qs.filter(status=TradeDocument.STATUS_PENDING, assigned_reviewer__isnull=True)).distinct()
            else:
                qs = qs.filter(uploader=user)
        total = qs.count()
        by_status = {}
        for status_choice, _ in TradeDocument.STATUS_CHOICES:
            by_status[status_choice] = qs.filter(status=status_choice).count()
        return Response({'total': total, 'by_status': by_status})

class UserPreferenceView(views.APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        pref, _ = UserPreference.objects.get_or_create(user=request.user)
        return Response(UserPreferenceSerializer(pref).data)

    def post(self, request):
        pref, _ = UserPreference.objects.get_or_create(user=request.user)
        serializer = UserPreferenceSerializer(pref, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)

class ToggleDarkModeView(views.APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        pref, _ = UserPreference.objects.get_or_create(user=request.user)
        pref.dark_mode = not pref.dark_mode
        pref.save()
        return Response({'dark_mode': pref.dark_mode})