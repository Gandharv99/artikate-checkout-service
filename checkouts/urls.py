from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import AssetViewSet, EmployeeViewSet, health_check

router = DefaultRouter()
router.register(r'assets', AssetViewSet, basename='asset')
router.register(r'employees', EmployeeViewSet, basename='employee')

urlpatterns = [
    path('health/', health_check, name='health_check'),
    path('', include(router.urls)),
]