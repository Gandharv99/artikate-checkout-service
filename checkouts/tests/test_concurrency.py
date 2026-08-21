import threading
import pytest
from django.db import connections
from checkouts.services import check_out
from checkouts.exceptions import ConflictException

@pytest.mark.django_db(transaction=True)
def test_simultaneous_checkout_only_one_succeeds(create_asset, create_employee, future_due_date):
    """
    Test that when two threads attempt to check out the same asset simultaneously,
    only one succeeds and the other raises a Conflict exception.
    """
    from checkouts.models import Employee

    # Create a second employee for the test
    second_employee = Employee.objects.create(
        employee_code="EMP-003", full_name="Alice Johnson",
        email="alice@artikate.com", is_active=True,
    )

    results = []

    def attempt_checkout(employee_code):
        try:
            check_out(create_asset.asset_tag, employee_code, future_due_date)
            results.append("success")
        except ConflictException:
            results.append("conflict")
        finally:
            # Close the connection to avoid "connection already closed" errors in threads
            connections.close_all()
    
    t1 = threading.Thread(target=attempt_checkout, args=(create_employee.employee_code,))
    t2 = threading.Thread(target=attempt_checkout, args=(second_employee.employee_code,))

    t1.start()
    t2.start()

    t1.join()
    t2.join()

    # Assert that one thread succeeded and the other raised a Conflict
    assert results.count("success") == 1
    assert results.count("conflict") == 1