# backend/documents/tasks.py
import tempfile
import traceback
from celery import shared_task
from django.conf import settings

from .models import DocumentFile, TradeDocument, ValidationResult, AuditLog
import fitz  # pymupdf
from pdf2image import convert_from_path
import pytesseract
from PIL import Image
import re
import os

# -------------------------------------------------------------------------
# NOTE: Adjust the REQUIRED_FIELDS mapping below to match your app's
#       expectations per document type. If your code already defines
#       REQUIRED_FIELDS, you can import it instead of using this.
# -------------------------------------------------------------------------
REQUIRED_FIELDS = {
    'invoice': ['hs_code', 'goods_description', 'value', 'currency'],
    'packing_list': ['packing_list_file'],
    'bol_awb': ['bol_awb_file'],
    'delivery_order': ['delivery_order_file'],
}
# If your TradeDocument.doc_type values differ (e.g., TradeDocument.TYPE_INVOICE),
# adapt the mapping keys accordingly.

def parse_text_for_metadata(text):
    """
    Heuristic parse of a text blob to extract keys:
    hs_code, value, currency, container_number, consignee, shipper, bol_awb_number
    """
    if not text:
        return {}
    res = {}
    s = text
    s_norm = re.sub(r'\s+', ' ', s)

    # HS code: prefer explicit "HS" prefix, else 6-digit fallback
    hs_candidates = re.findall(r'\bHS[:\s]*([0-9]{4,10})\b', s_norm, flags=re.IGNORECASE)
    if hs_candidates:
        res['hs_code'] = hs_candidates[0]
    else:
        fallback = re.findall(r'\b([0-9]{6})\b', s_norm)
        if fallback:
            res['hs_code'] = fallback[0]

    # Currency code
    cur_match = re.search(r'\b(AED|USD|EUR|GBP|JPY|CHF|SAR|INR)\b', s_norm)
    if cur_match:
        res['currency'] = cur_match.group(1)

    # Value (first currency-like amount)
    val_match = re.search(r'([£€$]?\s?[\d\.,]{3,}\b)', s_norm)
    if val_match:
        v = val_match.group(1)
        v_clean = re.sub(r'[^\d\.]', '', v)
        if v_clean:
            res['value'] = v_clean

    # Container number example: ABCD1234567
    cont = re.search(r'\b([A-Z]{4}\d{7})\b', s_norm)
    if cont:
        res['container_number'] = cont.group(1)

    # AWB/BOL common patterns
    awb = re.search(r'\b(AWB[:\s-]*\w+|\d{3}\s?\d{8}|\bAWB[\w-]{3,}\b)\b', s_norm, flags=re.IGNORECASE)
    if awb:
        res['bol_awb_number'] = awb.group(0).strip()

    # Consignee/shipper heuristics
    consignee = re.search(r'Consignee[:\s]*(.{1,80}?)\s{2,}', s, flags=re.IGNORECASE)
    if consignee:
        res['consignee'] = consignee.group(1).strip()
    else:
        m = re.search(r'Consignee[:\s]*(\w[\w\s\,\-\.]{1,80})', s, flags=re.IGNORECASE)
        if m:
            res['consignee'] = m.group(1).strip()

    shipper = re.search(r'Shipper[:\s]*(.{1,80}?)\s{2,}', s, flags=re.IGNORECASE)
    if shipper:
        res['shipper'] = shipper.group(1).strip()
    else:
        m2 = re.search(r'Shipper[:\s]*(\w[\w\s\,\-\.]{1,80})', s, flags=re.IGNORECASE)
        if m2:
            res['shipper'] = m2.group(1).strip()

    return res

def extract_text_with_pymupdf(path):
    """Extract text using PyMuPDF (non-OCR extraction)."""
    text_parts = []
    try:
        doc = fitz.open(path)
        for page in doc:
            txt = page.get_text()
            if txt:
                text_parts.append(txt)
    except Exception:
        return ""
    return "\n".join(text_parts).strip()

def ocr_pdf_images(path, dpi=200):
    """Convert PDF pages to images and OCR them with pytesseract."""
    text_parts = []
    with tempfile.TemporaryDirectory() as tmpdir:
        try:
            pages = convert_from_path(path, dpi=dpi, output_folder=tmpdir)
            for im in pages:
                text_parts.append(pytesseract.image_to_string(im))
        except Exception:
            try:
                im = Image.open(path)
                text_parts.append(pytesseract.image_to_string(im))
            except Exception:
                return ""
    return "\n".join([t for t in text_parts if t]).strip()

@shared_task(bind=True)
def extract_text_and_parse_task(self, document_file_id):
    """
    Celery task: extract text for a DocumentFile, parse metadata heuristically,
    merge metadata into parent TradeDocument (without overwriting existing keys),
    and run automated validation for the parent document.
    """
    try:
        df = DocumentFile.objects.select_related('document').get(pk=document_file_id)
    except DocumentFile.DoesNotExist:
        return {'error': 'DocumentFile not found', 'id': document_file_id}

    df.extraction_status = DocumentFile.STATUS_RUNNING
    df.save(update_fields=['extraction_status'])

    file_path = df.file.path
    extracted = ""

    try:
        extracted = extract_text_with_pymupdf(file_path)
        if not extracted or len(extracted.strip()) < 30:
            ocr_text = ocr_pdf_images(file_path)
            if ocr_text and len(ocr_text.strip()) > len(extracted):
                extracted = ocr_text

        df.extracted_text = extracted[:100000] if extracted else ''
        df.extraction_status = DocumentFile.STATUS_DONE
        df.save(update_fields=['extracted_text', 'extraction_status'])

        parsed = parse_text_for_metadata(extracted)
        if parsed:
            doc = df.document
            meta = doc.metadata or {}
            changed = False
            for k, v in parsed.items():
                if k not in meta or (not meta.get(k) and v):
                    meta[k] = v
                    changed = True
            if changed:
                doc.metadata = meta
                doc.save(update_fields=['metadata'])
                try:
                    AuditLog.objects.create(user=None, action='metadata_auto_extracted', details={'doc_id': doc.id, 'parsed': parsed})
                except Exception:
                    pass

        # run validation for the document (synchronous invocation)
        run_validation_for_document(df.document.id)
        return {'status': 'done', 'document_file_id': document_file_id, 'parsed': parsed}
    except Exception as exc:
        df.extraction_status = DocumentFile.STATUS_FAILED
        df.save(update_fields=['extraction_status'])
        try:
            AuditLog.objects.create(user=None, action='extraction_failed', details={'document_file_id': document_file_id, 'error': str(exc), 'trace': traceback.format_exc()})
        except Exception:
            pass
        return {'status': 'failed', 'error': str(exc)}

def run_validation_for_document(document_id):
    """
    Run cross-document metadata-based validation for the specified document and
    persist a ValidationResult and update TradeDocument.last_validation.
    """
    try:
        doc = TradeDocument.objects.get(pk=document_id)
    except TradeDocument.DoesNotExist:
        return None

    possible_keys = ['hs_code', 'consignee', 'container_number', 'value', 'currency', 'bol_awb_number', 'shipper']
    doc_meta = doc.metadata or {}
    results = {}

    # Determine required fields/colors for this doc_type (use mapping or existing logic)
    required = REQUIRED_FIELDS.get(doc.doc_type, [])
    existing_files = {f.field_name for f in doc.files.all()}
    missing_files = [f for f in required if f not in existing_files]
    results['missing_files'] = missing_files

    if not doc_meta:
        results['ready_for_approval'] = False
        results['reason'] = 'metadata_missing'
        results['message'] = 'Document has no metadata.'
        try:
            ValidationResult.objects.create(document=doc, result=results, run_by=None)
        except Exception:
            pass
        doc.last_validation = results
        doc.save(update_fields=['last_validation'])
        try:
            AuditLog.objects.create(user=None, action='run_validation_auto', details={'doc_id': doc.id, 'results': results})
        except Exception:
            pass
        return results

    match_keys = {k: str(doc_meta[k]).strip() for k in possible_keys if k in doc_meta and str(doc_meta[k]).strip() != ''}
    results['match_keys'] = match_keys

    required_types = ['invoice', 'packing_list', 'bol_awb', 'delivery_order']
    found = {}
    missing_types = []

    for dtype in required_types:
        if doc.doc_type == dtype:
            found[dtype] = {'doc_id': doc.id, 'matched': True}
            continue

        candidates = TradeDocument.objects.filter(uploader=doc.uploader, doc_type=dtype).exclude(pk=doc.pk)
        matched_candidate = None
        for cand in candidates:
            cand_meta = cand.metadata or {}
            all_keys_present = all((k in cand_meta and str(cand_meta[k]).strip() != '') for k in match_keys.keys())
            if not all_keys_present:
                continue
            mismatch = False
            for k, v in match_keys.items():
                if str(cand_meta.get(k, '')).strip() != v:
                    mismatch = True
                    break
            if not mismatch:
                matched_candidate = cand
                break

        if matched_candidate:
            found[dtype] = {'doc_id': matched_candidate.id, 'matched': True}
        else:
            found[dtype] = {'matched': False}
            missing_types.append(dtype)

    results['found_types'] = {k: v for k, v in found.items() if v.get('matched')}
    results['missing_types'] = missing_types

    ready = (len(missing_files) == 0) and (len(missing_types) == 0)
    results['ready_for_approval'] = ready

    if ready:
        results['message'] = 'All related documents found and consistent. Ready for approval.'
    else:
        msgs = []
        if missing_files:
            msgs.append(f"Missing files for this document: {missing_files}")
        if missing_types:
            msgs.append("Missing or unmatched document types: " + ", ".join(missing_types))
        results['message'] = " | ".join(msgs)

    try:
        ValidationResult.objects.create(document=doc, result=results, run_by=None)
    except Exception:
        pass
    doc.last_validation = results
    doc.save(update_fields=['last_validation'])
    try:
        AuditLog.objects.create(user=None, action='run_validation_auto', details={'doc_id': doc.id, 'results': results})
    except Exception:
        pass

    return results


