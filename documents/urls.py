from django.urls import path
from .views import DocumentUploadView, DocumentListView, DocumentDetailView, ApproveRejectView, RunValidationView, CommentCreateView, CommentListView, CurrencyConvertView, DocumentStatsView, UserPreferenceView, ToggleDarkModeView

urlpatterns = [
    path('upload/', DocumentUploadView.as_view(), name='documents-upload'),
    path('', DocumentListView.as_view(), name='documents-list'),
    path('<int:pk>/', DocumentDetailView.as_view(), name='documents-detail'),
    path('<int:pk>/approve_reject/', ApproveRejectView.as_view(), name='documents-approve-reject'),
    path('<int:pk>/validate/', RunValidationView.as_view(), name='documents-validate'),
    path('<int:pk>/comments/', CommentListView.as_view(), name='documents-comments'),
    path('comments/create/', CommentCreateView.as_view(), name='comments-create'),
    path('currency-convert/', CurrencyConvertView.as_view(), name='currency-convert'),
    path('document-stats/', DocumentStatsView.as_view(), name='document-stats'),
    path('user/preferences/', UserPreferenceView.as_view(), name='user-preferences'),
    path('user/preferences/toggle-dark-mode/', ToggleDarkModeView.as_view(), name='user-preferences-toggle-dark'),
]