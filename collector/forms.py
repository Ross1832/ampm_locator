from django import forms

from .models import UsefulInfo


class UsefulInfoForm(forms.ModelForm):
    class Meta:
        model = UsefulInfo
        fields = ["title", "description", "image"]
