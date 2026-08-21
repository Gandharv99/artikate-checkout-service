from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from checkouts.models import Asset, Employee, CheckOut


class Command(BaseCommand):
    help = "Seed the database with demo data for manual testing and the recording."

    def handle(self, *args, **options):
        now = timezone.now()

        # --- Assets: at least 8, across all 4 categories ---
        assets_data = [
            ("CAM-001", "Sony A7 III", Asset.Category.CAMERA),
            ("CAM-002", "Canon EOS R5", Asset.Category.CAMERA),
            ("LAP-001", "MacBook Pro 16\"", Asset.Category.LAPTOP),
            ("LAP-002", "Dell XPS 15", Asset.Category.LAPTOP),
            ("SEN-001", "Vibration Sensor V2", Asset.Category.SENSOR),
            ("SEN-002", "Temperature Sensor", Asset.Category.SENSOR),
            ("VEH-001", "Field Survey Jeep", Asset.Category.VEHICLE),
            ("VEH-002", "Delivery Van", Asset.Category.VEHICLE),
        ]
        assets = {}
        for tag, name, category in assets_data:
            asset, _ = Asset.objects.get_or_create(
                asset_tag=tag,
                defaults={
                    "name": name,
                    "category": category,
                    "purchase_date": "2026-08-01",
                },
            )
            assets[tag] = asset
        self.stdout.write(self.style.SUCCESS(f"Seeded {len(assets)} assets."))

        # --- Employees: at least 4, one inactive ---
        employees_data = [
            ("EMP-001", "Aditya Rawat", "aditya.rawat@artikate.com", True),
            ("EMP-002", "Priya Sharma", "priya.sharma@artikate.com", True),
            ("EMP-003", "Rohan Mehta", "rohan.mehta@artikate.com", True),
            ("EMP-004", "Neha Kapoor", "neha.kapoor@artikate.com", False),
        ]
        employees = {}
        for code, name, email, active in employees_data:
            emp, _ = Employee.objects.get_or_create(
                employee_code=code,
                defaults={"full_name": name, "email": email, "is_active": active},
            )
            employees[code] = emp
        self.stdout.write(self.style.SUCCESS(f"Seeded {len(employees)} employees."))

        # --- Checkouts: 2 overdue, 2 returned on time, 1 returned late ---
        self._reset_checkout_state(assets)

        # Overdue #1: due 5 days ago, still open
        self._make_checkout(
            assets["CAM-001"], employees["EMP-001"],
            checked_out_days_ago=10, due_in_days=-5, returned=False,
        )
        # Overdue #2: due 1 day ago, still open
        self._make_checkout(
            assets["CAM-002"], employees["EMP-002"],
            checked_out_days_ago=6, due_in_days=-1, returned=False,
        )
        # Returned on time #1
        self._make_checkout(
            assets["LAP-001"], employees["EMP-001"],
            checked_out_days_ago=15, due_in_days=10, returned=True, returned_days_ago=8,
        )
        # Returned on time #2
        self._make_checkout(
            assets["LAP-002"], employees["EMP-003"],
            checked_out_days_ago=20, due_in_days=14, returned=True, returned_days_ago=12,
        )
        # Returned LATE (was overdue, then returned)
        self._make_checkout(
            assets["SEN-001"], employees["EMP-002"],
            checked_out_days_ago=25, due_in_days=5, returned=True, returned_days_ago=3,
        )

        self.stdout.write(self.style.SUCCESS("Seeded checkouts (2 overdue, 2 on-time returns, 1 late return)."))
        self.stdout.write(self.style.SUCCESS("Demo data seeding complete."))

    def _reset_checkout_state(self, assets):
        """Safe re-run: clear existing checkouts/notices for these assets and
        reset their status, rather than accumulating duplicates on each run."""
        CheckOut.objects.filter(asset__in=assets.values()).delete()
        for asset in assets.values():
            asset.status = Asset.Status.AVAILABLE
            asset.save(update_fields=["status"])

    def _make_checkout(self, asset, employee, checked_out_days_ago, due_in_days,
                        returned, returned_days_ago=None):
        now = timezone.now()
        checkout = CheckOut.objects.create(
            asset=asset,
            employee=employee,
            due_at=now + timedelta(days=due_in_days),
            returned_at=(now - timedelta(days=returned_days_ago)) if returned else None,
        )
        # backdate checked_out_at manually since it's auto_now_add
        CheckOut.objects.filter(pk=checkout.pk).update(
            checked_out_at=now - timedelta(days=checked_out_days_ago)
        )
        asset.status = Asset.Status.AVAILABLE if returned else Asset.Status.CHECKED_OUT
        asset.save(update_fields=["status"])
        return checkout