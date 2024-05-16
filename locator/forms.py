from django import forms

from .models import Item


class UploadFileForm(forms.Form):
    file = forms.FileField()


class ItemForm(forms.ModelForm):
    class Meta:
        model = Item
        fields = ["model_prefix", "number", "line", "place"]
