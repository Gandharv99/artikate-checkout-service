from datetime import timedelta
from django.utils import timezone
from django.db import transaction
from rest_framework.exceptions import ValidationError, NotFound
from .exceptions import ConflictException
from .models import Asset, Employee, CheckOut

def _validate_due_date(due_at):
    now = timezone.now()
    if due_at <= now:
        raise ValidationError({"due_at": "Due date must be in the future."})
    if due_at > now + timedelta(days=30):
        raise ValidationError({"due_at": "Due date cannot be more than 30 days in the future."})


def check_out(asset_tag, employee_code, due_at):
    """
    Applies business rules 1, 2, 3, 4, 5, 7, 8 (A2).
    Order: existence checks -> cheap validation -> locked status/limit checks.
    The asset row is locked with select_for_update() *inside* the atomic block,
    so a second concurrent request for the same asset blocks until the first
    transaction commits, then sees the updated status and correctly gets 409 —
    this is what closes the race condition at the DB level (rule 7).
    """
    try:
        asset = Asset.objects.get(asset_tag=asset_tag)
    except Asset.DoesNotExist:
        raise NotFound({"asset_tag": f"Asset with tag '{asset_tag}' does not exist."})

    try:
        employee = Employee.objects.get(employee_code=employee_code)
    except Employee.DoesNotExist:
        raise NotFound({"employee_code": f"Employee with code '{employee_code}' does not exist."})
    
    if not employee.is_active:
        raise ValidationError({"employee_code": f"Employee with code '{employee_code}' is not active."})
    
    _validate_due_date(due_at)

    with transaction.atomic():
        # Re-fetch with row lock to prevent race conditions
        asset = Asset.objects.select_for_update().get(pk=asset.pk)
        employee = Employee.objects.select_for_update().get(pk=employee.pk)

        if asset.status != Asset.Status.AVAILABLE:
            raise ConflictException({"asset_tag": f"Asset with tag '{asset_tag}' is not available for checkout."})
        
        open_count = CheckOut.objects.filter(employee=employee, returned_at__isnull=True).count()
        if open_count >= 3:
            raise ConflictException({"employee_code": f"Employee with code '{employee_code}' has reached the checkout limit of 3 assets."})
        
        checkout = CheckOut.objects.create(asset=asset, employee=employee, due_at=due_at)
        asset.status = Asset.Status.CHECKED_OUT
        asset.save(update_fields=['status', 'updated_at'])
    
    return checkout


def return_asset(checkout_id, condition_note="", needs_maintenance=False):
    """
    Applies business rules 6: Returning sets returned_at to now and sets the asset back to AVAILABLE, or to MAINTENANCE if the request flags it.
    Returning an already-returned check-out -> 409 Conflict, plus the same DB-level locking pattern as check_out() to close the equivalent race condition on double-return.
    """
    with transaction.atomic():
        try:
            checkout = (
                CheckOut.objects.select_for_update()
                .select_related("asset", "employee")
                .get(pk=checkout_id)
            )
        except CheckOut.DoesNotExist:
            raise NotFound(f"No checkout with id '{checkout_id}'.")

        if checkout.returned_at is not None:
            raise ConflictException("This checkout has already been returned.")

        checkout.returned_at = timezone.now()
        checkout.condition_note = condition_note
        checkout.save(update_fields=["returned_at", "condition_note"])

        asset = Asset.objects.select_for_update().get(pk=checkout.asset_id)
        asset.status = (
            Asset.Status.MAINTENANCE if needs_maintenance else Asset.Status.AVAILABLE
        )
        asset.save(update_fields=["status", "updated_at"])

    return checkout