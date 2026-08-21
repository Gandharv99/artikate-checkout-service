import pytest
from checkouts.exceptions import ConflictException
from checkouts.services import check_out, return_asset
from checkouts.models import Asset

@pytest.mark.django_db
def test_return_success(create_asset, create_employee, future_due_date):
    checkout = check_out(create_asset.asset_tag, create_employee.employee_code, future_due_date)
    returned = return_asset(checkout.id, condition_note="Good condition", needs_maintenance=False)
    create_asset.refresh_from_db()
    assert returned.returned_at is not None
    assert create_asset.status == Asset.Status.AVAILABLE

@pytest.mark.django_db
def test_return_with_maintenance_flag(create_asset, create_employee, future_due_date):
    checkout = check_out(create_asset.asset_tag, create_employee.employee_code, future_due_date)
    return_asset(checkout.id, condition_note="Broken", needs_maintenance=True)
    create_asset.refresh_from_db()
    assert create_asset.status == Asset.Status.MAINTENANCE

@pytest.mark.django_db
def test_double_return_conflict(create_asset, create_employee, future_due_date):
    checkout = check_out(create_asset.asset_tag, create_employee.employee_code, future_due_date)
    return_asset(checkout.id)
    with pytest.raises(ConflictException):
        return_asset(checkout.id)