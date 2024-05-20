from django import forms

from .models import Item


class UploadFileForm(forms.Form):
    file = forms.FileField()


class UpdateFileForm(forms.Form):
    file = forms.FileField()


class ItemForm(forms.ModelForm):
    class Meta:
        model = Item
        fields = ['model_prefix', 'number', 'line', 'place']

    def clean(self):
        cleaned_data = super().clean()
        number = cleaned_data.get('number')
        model_prefix = cleaned_data.get('model_prefix')

        # Check if an item with the same number and model_prefix already exists
        if Item.objects.filter(number=number, model_prefix=model_prefix).exists():
            self.instance = Item.objects.get(number=number, model_prefix=model_prefix)

        return cleaned_data
