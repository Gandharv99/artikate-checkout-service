import pytest
from datetime import timedelta
from django.utils import timezone

from checkouts.services import check_out
from checkouts.tasks import flag_overdue_checkouts
from checkouts.models import OverdueNotice

@pytest.mark.django_db
def test_flag_overdue_checkouts_is_idempotent(create_asset, create_employee):
    past_due = timezone.now() + timedelta(seconds=1)
    checkout = check_out(create_asset.asset_tag, create_employee.employee_code, past_due)

    # force it into the past so it's actually overdue by the time the task runs
    from checkouts.models import CheckOut
    CheckOut.objects.filter(pk=checkout.pk).update(
        due_at=timezone.now() - timedelta(days=1)
    )

    flag_overdue_checkouts()
    flag_overdue_checkouts()  # run twice

    notices = OverdueNotice.objects.filter(checkout=checkout)
    assert notices.count() == 1