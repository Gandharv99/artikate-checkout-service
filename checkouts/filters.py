import django_filters
from .models import Asset

class AssetFilter(django_filters.FilterSet):
    status = django_filters.ChoiceFilter(choices=Asset.Status.choices)
    category = django_filters.ChoiceFilter(choices=Asset.Category.choices)

    class Meta:
        model = Asset
        fields = ['status', 'category']