from django.db import models
from django.urls import reverse

class Info(models.Model):
    title = models.CharField(max_length=200)
    description = models.TextField()
    image = models.ImageField(upload_to='info_images/', null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    def get_absolute_url(self):
        return reverse('info_detail', args=[str(self.id)])

    def __str__(self):
        return self.title

class UsefulInfo(models.Model):
    title = models.CharField(max_length=200)
    description = models.TextField()
    image = models.ImageField(upload_to="images/", blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(
        auto_now=True
    )

    def __str__(self):
        return self.title
