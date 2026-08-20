from django.db import connection
from rest_framework import viewsets, filters, status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from .models import Asset, Employee
from .serializers import AssetSerializer, EmployeeSerializer
from .filters import AssetFilter

# Create your views here.
class AssetViewSet(viewsets.ModelViewSet):
    queryset = Asset.objects.all().order_by("assest_tag")
    serializer_class = AssetSerializer
    filterset_class = AssetFilter
    search_fields = ['asset_tag', 'name']

class EmployeeViewSet(viewsets.ModelViewSet):
    queryset = Employee.objects.all().order_by("employee_code")
    serializer_class = EmployeeSerializer

@api_view(['GET'])
@permission_classes([AllowAny])
def health_check(request):
    db_ok = True
    try:
        connection.ensure_connection()
    except Exception:
        db_ok = False

    payload = {"status": "ok" if db_ok else "degraded", "database": db_ok}
    return Response(payload, status=status.HTTP_200_OK)
