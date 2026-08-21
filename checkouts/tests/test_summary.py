import pytest
from datetime import timedelta
from django.utils import timezone
from checkouts.models import CheckOut
from checkouts.selectors import employee_summary


@pytest.mark.django_db
def test_employee_summary_four_numbers(create_asset, create_employee):
    now = timezone.now()

    # Returned checkout 1: held 5 days
    c1 = CheckOut.objects.create(
        asset=create_asset, employee=create_employee,
        due_at=now - timedelta(days=1),
        returned_at=now - timedelta(days=5),
    )
    CheckOut.objects.filter(pk=c1.pk).update(checked_out_at=now - timedelta(days=10))

    # Returned checkout 2: held 8 days
    c2 = CheckOut.objects.create(
        asset=create_asset, employee=create_employee,
        due_at=now - timedelta(days=5),
        returned_at=now - timedelta(days=12),
    )
    CheckOut.objects.filter(pk=c2.pk).update(checked_out_at=now - timedelta(days=20))

    # Open, not yet due
    CheckOut.objects.create(
        asset=create_asset, employee=create_employee,
        due_at=now + timedelta(days=3), returned_at=None,
    )

    # Open, overdue
    CheckOut.objects.create(
        asset=create_asset, employee=create_employee,
        due_at=now - timedelta(days=2), returned_at=None,
    )

    result = employee_summary(create_employee)

    assert result["lifetime_checkouts"] == 4
    assert result["currently_held"] == 2
    assert result["currently_overdue"] == 1
    # mean of 5 and 8 day holds = 6.5
    assert result["mean_hold_duration_days"] == pytest.approx(6.5, abs=0.01)