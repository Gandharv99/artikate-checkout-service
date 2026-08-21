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

class CheckOutCreateSerializer(serializers.Serializer):
    asset_tag = serializers.CharField()
    employee_code = serializers.CharField()
    due_at = serializers.DateTimeField()

class CheckOutSerializer(serializers.ModelSerializer):
    asset_tag = serializers.CharField(source='asset.asset_tag', read_only=True)
    employee_code = serializers.CharField(source='employee.employee_code', read_only=True)

    class Meta:
        model = CheckOut
        fields = ['id', 'asset_tag', 'employee_code', "checked_out_at", 'due_at', 'returned_at', 'condition_note',]

class ReturnSerializer(serializers.Serializer):
    condition_note = serializers.CharField(required=False, allow_blank=True, default="")
    needs_maintenance = serializers.BooleanField(required=False, default=False)