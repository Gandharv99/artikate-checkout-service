from django.db import connection
from rest_framework import viewsets, filters, status
from rest_framework.generics import get_object_or_404
from rest_framework.decorators import api_view, permission_classes, action
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from .models import Asset, Employee
from .serializers import AssetSerializer, EmployeeSerializer, CheckOutSerializer, CheckOutCreateSerializer, ReturnSerializer, EmployeeSummarySerializer, OverdueCheckoutSerializer
from .services import check_out, return_asset
from .selectors import employee_summary, overdue_checkouts_queryset
from .filters import AssetFilter

# Create your views here.
class AssetViewSet(viewsets.ModelViewSet):
    queryset = Asset.objects.all().order_by("asset_tag")
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

class CheckOutViewSet(viewsets.ViewSet):

    def create(self, request):
        input_serializer = CheckOutCreateSerializer(data=request.data)
        input_serializer.is_valid(raise_exception=True)
        checkout = check_out(**input_serializer.validated_data)
        return Response(CheckOutSerializer(checkout).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['post'], url_path='return')
    def return_asset(self, request, pk=None):
        input_serializer = ReturnSerializer(data=request.data)
        input_serializer.is_valid(raise_exception=True)
        checkout = return_asset(checkout_id=pk, **input_serializer.validated_data)
        return Response(CheckOutSerializer(checkout).data, status=status.HTTP_200_OK)

@api_view(["GET"])
def employee_summary_view(request, employee_code):
    employee = get_object_or_404(Employee, employee_code=employee_code)
    data = employee_summary(employee)
    return Response(EmployeeSummarySerializer(data).data)


@api_view(["GET"])
def overdue_report_view(request):
    checkouts = overdue_checkouts_queryset()
    serializer = OverdueCheckoutSerializer(checkouts, many=True)
    return Response({"count": len(serializer.data), "results": serializer.data})