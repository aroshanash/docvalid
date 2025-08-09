from django.db import models
from django.contrib.auth.models import AbstractUser

class User(AbstractUser):
    ROLE_ADMIN = 'admin'
    ROLE_UPLOADER = 'uploader'
    ROLE_REVIEWER = 'reviewer'
    ROLE_CHOICES = [
        (ROLE_ADMIN, 'Admin'),
        (ROLE_UPLOADER, 'Uploader'),
        (ROLE_REVIEWER, 'Reviewer'),
    ]

    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default=ROLE_UPLOADER)

    def is_admin(self):
        return self.role == self.ROLE_ADMIN

    def is_uploader(self):
        return self.role == self.ROLE_UPLOADER

    def is_reviewer(self):
        return self.role == self.ROLE_REVIEWER