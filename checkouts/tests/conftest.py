import pytest
from django.utils import timezone
from datetime import timedelta
from checkouts.models import Asset, Employee, CheckOut

@pytest.fixture
def create_asset(db):
    return Asset.objects.create(
        asset_tag="CAM-001", name="Sony A7 III",
        category=Asset.Category.CAMERA, purchase_date="2026-08-01",
    )

@pytest.fixture
def create_employee(db):
    return Employee.objects.create(
        employee_code="EMP-001", full_name="John Doe",
        email="john@artikate.com", is_active=True,
    )

@pytest.fixture
def inactive_employee(db):
    return Employee.objects.create(
        employee_code="EMP-002", full_name="Jane Smith",
        email="jane@artikate.com", is_active=False,
    )

@pytest.fixture
def future_due_date():
    return timezone.now() + timedelta(days=5)