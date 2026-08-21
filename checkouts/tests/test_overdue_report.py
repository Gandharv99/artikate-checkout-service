import pytest
from datetime import timedelta
from django.utils import timezone
from checkouts.models import CheckOut
from checkouts.selectors import overdue_checkouts_queryset


@pytest.mark.django_db
def test_overdue_report_boundary_and_exclusions(create_asset, create_employee):
    now = timezone.now()

    # Due exactly "now" at creation time. By the moment the queryset actually
    # executes a fraction of a second later, real time has moved past this
    # due_at -- so it must be included. This is the explicit "due exactly
    # now" edge case A5 asks for.
    due_now = CheckOut.objects.create(
        asset=create_asset, employee=create_employee, due_at=now, returned_at=None,
    )

    # Due in the future -- must NOT appear.
    CheckOut.objects.create(
        asset=create_asset, employee=create_employee,
        due_at=now + timedelta(hours=1), returned_at=None,
    )

    # Overdue but already returned -- must NOT appear.
    CheckOut.objects.create(
        asset=create_asset, employee=create_employee,
        due_at=now - timedelta(days=1), returned_at=now,
    )

    # Clearly overdue and open -- must appear, and first (most overdue).
    clearly_overdue = CheckOut.objects.create(
        asset=create_asset, employee=create_employee,
        due_at=now - timedelta(days=3), returned_at=None,
    )

    results = list(overdue_checkouts_queryset())
    result_ids = [c.id for c in results]

    assert len(results) == 2
    assert due_now.id in result_ids
    assert clearly_overdue.id in result_ids
    # most overdue first -> earliest due_at first
    assert results[0].id == clearly_overdue.id
    assert results[1].id == due_now.id