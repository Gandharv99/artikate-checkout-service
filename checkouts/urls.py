from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import AssetViewSet, EmployeeViewSet, health_check, CheckOutViewSet, employee_summary_view, overdue_report_view

router = DefaultRouter()
router.register(r'assets', AssetViewSet, basename='asset')
router.register(r'employees', EmployeeViewSet, basename='employee')
router.register(r'checkouts', CheckOutViewSet, basename='checkout')

urlpatterns = [
    path('health/', health_check, name='health_check'),
    path("employees/<str:employee_code>/summary/", employee_summary_view, name="employee-summary"),
    path("reports/overdue/", overdue_report_view, name="overdue-report"),
    path('', include(router.urls)),
]