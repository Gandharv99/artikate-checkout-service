from django.db import models
from django.db.models import Count, Avg, F, Q, ExpressionWrapper, DurationField
from django.utils import timezone

from .models import CheckOut

def employee_summary(employee):
    """
    Single ORM aggregation query — no Python loop.
    - lifetime_checkouts: total checkouts ever
    - currently_held: open checkouts (returned_at is null)
    - currently_overdue: open AND past due_at
    - mean_hold_duration_days: avg (returned_at - checked_out_at) over RETURNED items only
    """
    now = timezone.now()

    hold_duration = ExpressionWrapper(
        F('returned_at') - F('checked_out_at'),
        output_field=DurationField()
    )

    result = CheckOut.objects.filter(employee=employee).aggregate(
        lifetime_checkouts=Count("id"),
        currently_held=Count("id", filter=Q(returned_at__isnull=True)),
        currently_overdue=Count(
            "id", filter=Q(returned_at__isnull=True, due_at__lt=now)
        ),
        mean_hold_duration=Avg(
            hold_duration, filter=Q(returned_at__isnull=False)
        ),
    )

    mean_days = None
    if result["mean_hold_duration"] is not None:
        mean_days = round(result["mean_hold_duration"].total_seconds() / 86400, 2)

    return {
        "lifetime_checkouts": result["lifetime_checkouts"],
        "currently_held": result["currently_held"],
        "currently_overdue": result["currently_overdue"],
        "mean_hold_duration_days": mean_days,
    }

def overdue_checkouts_queryset():
    """
    All open checkouts past due_at, most overdue first.
    select_related avoids a query per row for asset/employee.
    """
    now = timezone.now()
    return (
        CheckOut.objects.filter(returned_at__isnull=True, due_at__lt=now)
        .select_related("asset", "employee")
        .order_by("due_at")
    )