from rest_framework import serializers
from .models import Asset, Employee, CheckOut, OverdueNotice

class EmployeeSerializer(serializers.ModelSerializer):
    class Meta:
        model = Employee
        fields = ['id', 'employee_code', 'full_name', 'email', 'is_active']

class AssetSerializer(serializers.ModelSerializer):
    current_holder = serializers.SerializerMethodField()

    class Meta:
        model = Asset
        fields = [
            "id", "asset_tag", "name", "category", "status", "purchase_date", "current_holder", "created_at", "updated_at", 
        ]
        read_only_fields = ["status", "created_at", "updated_at"]

    def get_current_holder(self, obj):
        open_checkout = obj.checkouts.filter(returned_at__isnull=True).select_related('employee').first()
        if open_checkout is None:
            return None
        return {
            "employee_code": open_checkout.employee.employee_code,
            "full_name": open_checkout.employee.full_name,
        }