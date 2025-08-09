# backend/workikai_project/celery.py
import os
from celery import Celery

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'workikai_project.settings')

from django.conf import settings  # noqa

app = Celery('workikai_project')
# Broker / backend configured with environment variables (fallback to local redis)
app.conf.broker_url = os.getenv('CELERY_BROKER_URL', getattr(settings, 'CELERY_BROKER_URL', 'redis://127.0.0.1:6379/0'))
app.conf.result_backend = os.getenv('CELERY_RESULT_BACKEND', getattr(settings, 'CELERY_RESULT_BACKEND', app.conf.broker_url))
app.conf.task_serializer = 'json'
app.conf.result_serializer = 'json'
app.conf.accept_content = ['json']
app.autodiscover_tasks()
