from celery import shared_task
from django.utils import timezone

from .models import CheckOut, OverdueNotice


@shared_task
def flag_overdue_checkouts():
    """
    Creates an OverdueNotice for every open, overdue checkout, dated today.
    Idempotent by construction: get_or_create against the (checkout, notice_date)
    unique constraint on OverdueNotice means re-running this five times in one
    day cannot produce more than one notice per checkout — the DB enforces it,
    not application logic.
    """
    today = timezone.localdate()
    overdue = CheckOut.objects.filter(
        returned_at__isnull=True,
        due_at__lt=timezone.now(),
    )

    created_count = 0
    for checkout in overdue:
        _, created = OverdueNotice.objects.get_or_create(
            checkout=checkout,
            notice_date=today,
        )
        if created:
            created_count += 1

    return f"Processed {overdue.count()} overdue checkouts, created {created_count} new notices."