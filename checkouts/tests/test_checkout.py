import pytest
from datetime import timedelta
from django.utils import timezone
from rest_framework.exceptions import NotFound, ValidationError
from checkouts.exceptions import ConflictException
from checkouts.services import check_out
from checkouts.models import Asset, Employee, CheckOut

@pytest.mark.django_db
def test_checkout_success(create_asset, create_employee, future_due_date):
    checkout = check_out(create_asset.asset_tag, create_employee.employee_code, future_due_date)
    create_asset.refresh_from_db()
    assert create_asset.status == Asset.Status.CHECKED_OUT
    assert checkout.asset_id == create_asset.id

@pytest.mark.django_db
def test_checkout_unavailable_asset_conflicts(create_asset, create_employee, future_due_date):
    check_out(create_asset.asset_tag, create_employee.employee_code, future_due_date)
    with pytest.raises(ConflictException):
        check_out(create_asset.asset_tag, create_employee.employee_code, future_due_date)

@pytest.mark.django_db
def test_checkout_inactive_employee_rejected(create_asset, inactive_employee, future_due_date):
    with pytest.raises(ValidationError):
        check_out(create_asset.asset_tag, inactive_employee.employee_code, future_due_date)

@pytest.mark.django_db
def test_checkout_unknown_asset_404(create_employee, future_due_date):
    with pytest.raises(NotFound):
        check_out("UNKNOWN_TAG", create_employee.employee_code, future_due_date)

@pytest.mark.django_db
def test_checkout_unknown_employee_404(create_asset, future_due_date):
    with pytest.raises(NotFound):
        check_out(create_asset.asset_tag, "UNKNOWN_EMP", future_due_date)

@pytest.mark.django_db
def test_checkout_past_due_at_rejected(create_asset, create_employee):
    past_due_date = timezone.now() - timedelta(days=1)
    with pytest.raises(ValidationError):
        check_out(create_asset.asset_tag, create_employee.employee_code, past_due_date)

@pytest.mark.django_db
def test_checkout_due_at_too_far_in_future_rejected(create_asset, create_employee):
    future_due_date = timezone.now() + timedelta(days=31)
    with pytest.raises(ValidationError):
        check_out(create_asset.asset_tag, create_employee.employee_code, future_due_date)

@pytest.mark.django_db
def test_checkout_three_open_limits(create_employee, future_due_date):
    assets = [Asset.objects.create(asset_tag=f"ASSET-{i}", name=f"Asset {i}", category=Asset.Category.CAMERA, purchase_date="2026-08-01") for i in range(4)]
    for a in assets[:3]:
        check_out(a.asset_tag, create_employee.employee_code, future_due_date)
    
    with pytest.raises(ConflictException):
        check_out(assets[3].asset_tag, create_employee.employee_code, future_due_date)