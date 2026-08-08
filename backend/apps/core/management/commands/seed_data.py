from datetime import timedelta
from decimal import Decimal
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from apps.accounts.models import Tenant, User
from apps.billing.models import Discount, Invoice, InvoiceLineItem, Payment
from apps.core.models import PlatformConfig
from apps.core.roles import Role
from apps.core.tenancy import tenant_context
from apps.operations.models import Complaint, ComplaintComment, Visitor
from apps.properties.models import (
    Bed,
    Building,
    Floor,
    Property,
    PropertySettings,
    PropertyStaffAssignment,
    Room,
)
from apps.residents.models import Admission, Allocation, Resident, Vacate
from apps.subscriptions.models import Subscription


class Command(BaseCommand):
    help = 'Idempotently seeds test data (users, tenant, properties, residents, complaints, financials, etc.)'

    @transaction.atomic
    def handle(self, *args, **options):
        self.stdout.write(self.style.MIGRATE_HEADING('Starting idempotent test data seeding...'))

        # 1. Platform Config & Admin User
        config = PlatformConfig.get()
        admin_email = 'admin@gmail.com'
        admin_user, created = User.objects.get_or_create(
            email=admin_email,
            defaults={
                'first_name': 'Super',
                'last_name': 'Admin',
                'role': Role.SUPER_ADMIN,
                'tenant': None,
                'is_staff': True,
                'is_superuser': True,
                'email_verified': True,
                'is_active': True,
            },
        )
        admin_user.set_password('Test@123')
        admin_user.role = Role.SUPER_ADMIN
        admin_user.tenant = None
        admin_user.is_staff = True
        admin_user.is_superuser = True
        admin_user.email_verified = True
        admin_user.is_active = True
        admin_user.save()
        self.stdout.write(f'  [Admin User] {admin_email} (created: {created})')

        # 2. Tenant & Tenant Users
        tenant, t_created = Tenant.objects.get_or_create(
            name='Sunshine Luxury PG',
            defaults={
                'default_language': 'en',
                'trial_ends_at': timezone.now() + timedelta(days=config.trial_days),
            },
        )
        Subscription.objects.get_or_create(tenant=tenant)
        self.stdout.write(f'  [Tenant] {tenant.name} (ID: {tenant.id})')

        # Owner (user@gmail.com)
        owner_email = 'user@gmail.com'
        owner, owner_created = User.objects.get_or_create(
            email=owner_email,
            defaults={
                'first_name': 'PG',
                'last_name': 'Owner',
                'role': Role.OWNER,
                'tenant': tenant,
                'is_staff': False,
                'is_superuser': False,
                'email_verified': True,
                'is_active': True,
            },
        )
        owner.set_password('Test@123')
        owner.role = Role.OWNER
        owner.tenant = tenant
        owner.email_verified = True
        owner.is_active = True
        owner.save()
        self.stdout.write(f'  [Owner User] {owner_email} (created: {owner_created})')

        # Manager
        manager_email = 'manager@gmail.com'
        manager, mgr_created = User.objects.get_or_create(
            email=manager_email,
            defaults={
                'first_name': 'Rajesh',
                'last_name': 'Kumar',
                'role': Role.MANAGER,
                'tenant': tenant,
                'is_staff': False,
                'is_superuser': False,
                'email_verified': True,
                'is_active': True,
            },
        )
        manager.set_password('Test@123')
        manager.role = Role.MANAGER
        manager.tenant = tenant
        manager.email_verified = True
        manager.is_active = True
        manager.save()
        self.stdout.write(f'  [Manager User] {manager_email}')

        # Receptionist
        receptionist_email = 'receptionist@gmail.com'
        receptionist, rec_created = User.objects.get_or_create(
            email=receptionist_email,
            defaults={
                'first_name': 'Sunita',
                'last_name': 'Verma',
                'role': Role.RECEPTIONIST,
                'tenant': tenant,
                'is_staff': False,
                'is_superuser': False,
                'email_verified': True,
                'is_active': True,
            },
        )
        receptionist.set_password('Test@123')
        receptionist.role = Role.RECEPTIONIST
        receptionist.tenant = tenant
        receptionist.email_verified = True
        receptionist.is_active = True
        receptionist.save()
        self.stdout.write(f'  [Receptionist User] {receptionist_email}')

        # Wrap all tenant-scoped DB operations in tenant_context
        with tenant_context(tenant_id=tenant.id, is_super_admin=True):
            # 3. Properties, Buildings, Floors, Rooms, Beds
            prop1, _ = Property.objects.get_or_create(
                name='Sunshine Boys PG (HSR Layout)',
                tenant_id=tenant.id,
                defaults={
                    'property_type': Property.PropertyType.BOYS_HOSTEL,
                    'address_line': '123, 27th Main Road, Sector 1, HSR Layout',
                    'city': 'Bengaluru',
                    'state': 'Karnataka',
                    'country': 'India',
                    'contact_number': '+919876543210',
                    'contact_email': 'hsr@sunshinepg.com',
                    'status': Property.Status.ACTIVE,
                },
            )
            PropertySettings.objects.get_or_create(property=prop1, tenant_id=tenant.id)

            prop2, _ = Property.objects.get_or_create(
                name='Greenwood Girls Hostel (Koramangala)',
                tenant_id=tenant.id,
                defaults={
                    'property_type': Property.PropertyType.GIRLS_HOSTEL,
                    'address_line': '45, 80 Feet Road, 4th Block, Koramangala',
                    'city': 'Bengaluru',
                    'state': 'Karnataka',
                    'country': 'India',
                    'contact_number': '+919876543211',
                    'contact_email': 'koramangala@sunshinepg.com',
                    'status': Property.Status.ACTIVE,
                },
            )
            PropertySettings.objects.get_or_create(property=prop2, tenant_id=tenant.id)

            # Staff Assignments
            PropertyStaffAssignment.objects.get_or_create(
                staff=manager, property=prop1, tenant_id=tenant.id
            )
            PropertyStaffAssignment.objects.get_or_create(
                staff=manager, property=prop2, tenant_id=tenant.id
            )
            PropertyStaffAssignment.objects.get_or_create(
                staff=receptionist, property=prop1, tenant_id=tenant.id
            )
            self.stdout.write(f'  [Properties Created] {prop1.name}, {prop2.name}')

            # Building & Floors for Prop 1
            bld1, _ = Building.objects.get_or_create(
                property=prop1, name='Main Block', tenant_id=tenant.id, defaults={'order': 1}
            )
            flr1_1, _ = Floor.objects.get_or_create(
                building=bld1, name='1st Floor', tenant_id=tenant.id, defaults={'order': 1}
            )
            flr1_2, _ = Floor.objects.get_or_create(
                building=bld1, name='2nd Floor', tenant_id=tenant.id, defaults={'order': 2}
            )

            # Rooms & Beds for Prop 1
            room101, _ = Room.objects.get_or_create(
                floor=flr1_1,
                room_number='101',
                tenant_id=tenant.id,
                defaults={
                    'sharing_type': Room.SharingType.TWO,
                    'category': Room.Category.AC,
                    'rack_rate_with_food': Decimal('10000.00'),
                    'rack_rate_without_food': Decimal('8500.00'),
                },
            )
            bed101_a, _ = Bed.objects.get_or_create(
                room=room101, bed_number='101-A', tenant_id=tenant.id
            )
            bed101_b, _ = Bed.objects.get_or_create(
                room=room101, bed_number='101-B', tenant_id=tenant.id
            )

            room102, _ = Room.objects.get_or_create(
                floor=flr1_1,
                room_number='102',
                tenant_id=tenant.id,
                defaults={
                    'sharing_type': Room.SharingType.THREE,
                    'category': Room.Category.NON_AC,
                    'rack_rate_with_food': Decimal('7500.00'),
                    'rack_rate_without_food': Decimal('6000.00'),
                },
            )
            bed102_a, _ = Bed.objects.get_or_create(
                room=room102, bed_number='102-A', tenant_id=tenant.id
            )
            bed102_b, _ = Bed.objects.get_or_create(
                room=room102, bed_number='102-B', tenant_id=tenant.id
            )
            bed102_c, _ = Bed.objects.get_or_create(
                room=room102, bed_number='102-C', tenant_id=tenant.id
            )

            room201, _ = Room.objects.get_or_create(
                floor=flr1_2,
                room_number='201',
                tenant_id=tenant.id,
                defaults={
                    'sharing_type': Room.SharingType.ONE,
                    'category': Room.Category.AC,
                    'rack_rate_with_food': Decimal('15000.00'),
                    'rack_rate_without_food': Decimal('13000.00'),
                },
            )
            bed201_a, _ = Bed.objects.get_or_create(
                room=room201, bed_number='201-A', tenant_id=tenant.id
            )

            # Building & Floors for Prop 2
            bld2, _ = Building.objects.get_or_create(
                property=prop2, name='Block A', tenant_id=tenant.id, defaults={'order': 1}
            )
            flr2_1, _ = Floor.objects.get_or_create(
                building=bld2, name='Ground Floor', tenant_id=tenant.id, defaults={'order': 0}
            )
            room_g01, _ = Room.objects.get_or_create(
                floor=flr2_1,
                room_number='G01',
                tenant_id=tenant.id,
                defaults={
                    'sharing_type': Room.SharingType.TWO,
                    'category': Room.Category.AC,
                    'rack_rate_with_food': Decimal('12000.00'),
                    'rack_rate_without_food': Decimal('10000.00'),
                },
            )
            bed_g01_a, _ = Bed.objects.get_or_create(
                room=room_g01, bed_number='G01-A', tenant_id=tenant.id
            )
            bed_g01_b, _ = Bed.objects.get_or_create(
                room=room_g01, bed_number='G01-B', tenant_id=tenant.id
            )
            self.stdout.write('  [Rooms & Beds] Created rooms 101, 102, 201, G01 and corresponding beds.')

            # 4. Residents, Admissions & Allocations
            today = timezone.now().date()
            thirty_days_ago = today - timedelta(days=30)
            fortyfive_days_ago = today - timedelta(days=45)
            sixty_days_ago = today - timedelta(days=60)

            # Resident 1: Rahul Sharma (Active)
            res1, _ = Resident.objects.get_or_create(
                phone='9876543210',
                tenant_id=tenant.id,
                defaults={
                    'property': prop1,
                    'first_name': 'Rahul',
                    'last_name': 'Sharma',
                    'gender': Resident.Gender.MALE,
                    'date_of_birth': today - timedelta(days=9000),
                    'email': 'rahul.sharma@example.com',
                    'permanent_address': 'Flat 301, Sunshine Heights, Jaipur, Rajasthan',
                    'current_address': 'Room 101, Sunshine Boys PG, HSR Layout, Bengaluru',
                    'emergency_contact_name': 'Ramesh Sharma',
                    'emergency_contact_relation': 'Father',
                    'emergency_contact_phone': '9876500001',
                    'aadhaar_number': '123456789012',
                    'status': Resident.Status.ACTIVE,
                },
            )
            res1.status = Resident.Status.ACTIVE
            res1.save()

            Admission.objects.get_or_create(
                resident=res1,
                tenant_id=tenant.id,
                defaults={
                    'bed': bed101_a,
                    'joining_date': thirty_days_ago,
                    'billing_mode': Admission.BillingMode.MONTHLY,
                    'expected_stay_duration': '6 months',
                    'contracted_sharing_type': Room.SharingType.TWO,
                    'contracted_room_category': Room.Category.AC,
                    'food_preference': Admission.FoodPreference.WITH_FOOD,
                    'contracted_rent': Decimal('10000.00'),
                    'advance_amount': Decimal('10000.00'),
                    'advance_collected_date': thirty_days_ago,
                    'advance_mode': Admission.AdvanceMode.UPI,
                    'recorded_by': owner,
                },
            )
            Allocation.objects.get_or_create(
                resident=res1,
                tenant_id=tenant.id,
                defaults={
                    'allocated_bed': bed101_a,
                    'contracted_sharing_type': Room.SharingType.TWO,
                    'contracted_room_category': Room.Category.AC,
                    'contracted_rent': Decimal('10000.00'),
                },
            )
            bed101_a.status = Bed.Status.OCCUPIED
            bed101_a.save()

            # Resident 2: Priya Patel (Active)
            res2, _ = Resident.objects.get_or_create(
                phone='9876543211',
                tenant_id=tenant.id,
                defaults={
                    'property': prop2,
                    'first_name': 'Priya',
                    'last_name': 'Patel',
                    'gender': Resident.Gender.FEMALE,
                    'date_of_birth': today - timedelta(days=8500),
                    'email': 'priya.patel@example.com',
                    'permanent_address': '12 Sector 4, Gandhinagar, Gujarat',
                    'current_address': 'Room G01, Greenwood Girls Hostel, Koramangala, Bengaluru',
                    'emergency_contact_name': 'Suresh Patel',
                    'emergency_contact_relation': 'Father',
                    'emergency_contact_phone': '9876500002',
                    'aadhaar_number': '234567890123',
                    'status': Resident.Status.ACTIVE,
                },
            )
            res2.status = Resident.Status.ACTIVE
            res2.save()

            Admission.objects.get_or_create(
                resident=res2,
                tenant_id=tenant.id,
                defaults={
                    'bed': bed_g01_a,
                    'joining_date': fortyfive_days_ago,
                    'billing_mode': Admission.BillingMode.MONTHLY,
                    'expected_stay_duration': '1 year',
                    'contracted_sharing_type': Room.SharingType.TWO,
                    'contracted_room_category': Room.Category.AC,
                    'food_preference': Admission.FoodPreference.WITH_FOOD,
                    'contracted_rent': Decimal('12000.00'),
                    'advance_amount': Decimal('12000.00'),
                    'advance_collected_date': fortyfive_days_ago,
                    'advance_mode': Admission.AdvanceMode.BANK_TRANSFER,
                    'recorded_by': owner,
                },
            )
            Allocation.objects.get_or_create(
                resident=res2,
                tenant_id=tenant.id,
                defaults={
                    'allocated_bed': bed_g01_a,
                    'contracted_sharing_type': Room.SharingType.TWO,
                    'contracted_room_category': Room.Category.AC,
                    'contracted_rent': Decimal('12000.00'),
                },
            )
            bed_g01_a.status = Bed.Status.OCCUPIED
            bed_g01_a.save()

            # Resident 3: Amit Kumar (Notice Period)
            res3, _ = Resident.objects.get_or_create(
                phone='9876543212',
                tenant_id=tenant.id,
                defaults={
                    'property': prop1,
                    'first_name': 'Amit',
                    'last_name': 'Kumar',
                    'gender': Resident.Gender.MALE,
                    'date_of_birth': today - timedelta(days=9500),
                    'email': 'amit.kumar@example.com',
                    'permanent_address': '55 Park Street, Patna, Bihar',
                    'current_address': 'Room 101, Sunshine Boys PG, HSR Layout, Bengaluru',
                    'emergency_contact_name': 'Sunil Kumar',
                    'emergency_contact_relation': 'Father',
                    'emergency_contact_phone': '9876500003',
                    'aadhaar_number': '345678901234',
                    'status': Resident.Status.NOTICE_PERIOD,
                },
            )
            res3.status = Resident.Status.NOTICE_PERIOD
            res3.save()

            Admission.objects.get_or_create(
                resident=res3,
                tenant_id=tenant.id,
                defaults={
                    'bed': bed101_b,
                    'joining_date': sixty_days_ago,
                    'billing_mode': Admission.BillingMode.MONTHLY,
                    'expected_stay_duration': '3 months',
                    'contracted_sharing_type': Room.SharingType.TWO,
                    'contracted_room_category': Room.Category.AC,
                    'food_preference': Admission.FoodPreference.WITHOUT_FOOD,
                    'contracted_rent': Decimal('8500.00'),
                    'advance_amount': Decimal('8500.00'),
                    'advance_collected_date': sixty_days_ago,
                    'advance_mode': Admission.AdvanceMode.CASH,
                    'recorded_by': manager,
                },
            )
            Allocation.objects.get_or_create(
                resident=res3,
                tenant_id=tenant.id,
                defaults={
                    'allocated_bed': bed101_b,
                    'contracted_sharing_type': Room.SharingType.TWO,
                    'contracted_room_category': Room.Category.AC,
                    'contracted_rent': Decimal('8500.00'),
                },
            )
            bed101_b.status = Bed.Status.OCCUPIED
            bed101_b.save()

            Vacate.objects.get_or_create(
                resident=res3,
                tenant_id=tenant.id,
                defaults={
                    'notice_given_date': today - timedelta(days=10),
                    'expected_vacate_date': today + timedelta(days=20),
                },
            )

            # Resident 4: Sneha Reddy (Inquiry)
            res4, _ = Resident.objects.get_or_create(
                phone='9876543213',
                tenant_id=tenant.id,
                defaults={
                    'property': prop2,
                    'first_name': 'Sneha',
                    'last_name': 'Reddy',
                    'gender': Resident.Gender.FEMALE,
                    'email': 'sneha.reddy@example.com',
                    'current_address': 'Koramangala, Bengaluru',
                    'status': Resident.Status.INQUIRY,
                },
            )
            self.stdout.write('  [Residents] Created Rahul Sharma (Active), Priya Patel (Active), Amit Kumar (Notice), Sneha Reddy (Inquiry).')

            # 5. Financials (Discounts, Invoices, Line Items, Payments)
            # Discount for Rahul Sharma
            Discount.objects.get_or_create(
                resident=res1,
                tenant_id=tenant.id,
                defaults={
                    'discount_type': Discount.DiscountType.FIXED,
                    'discount_value': Decimal('500.00'),
                    'reason': Discount.Reason.LOYALTY,
                    'note': 'Loyalty discount applied for long stay agreement',
                    'valid_from': thirty_days_ago,
                    'approved_by': owner,
                },
            )

            # Current billing cycle setup
            period_start = today.replace(day=1)
            next_month = (period_start + timedelta(days=32)).replace(day=1)
            period_end = next_month - timedelta(days=1)
            due_date = period_start + timedelta(days=5)

            # Invoice 1 (Rahul Sharma) - Paid
            inv1, _ = Invoice.objects.get_or_create(
                resident=res1,
                period_start=period_start,
                tenant_id=tenant.id,
                defaults={
                    'period_end': period_end,
                    'billing_mode': Admission.BillingMode.MONTHLY,
                    'issue_date': period_start,
                    'due_date': due_date,
                    'status': Invoice.Status.ISSUED,
                    'notes': 'Monthly rent for current period',
                    'created_by': owner,
                },
            )
            InvoiceLineItem.objects.get_or_create(
                invoice=inv1,
                line_type=InvoiceLineItem.LineType.ACCOMMODATION,
                tenant_id=tenant.id,
                defaults={'label': 'Monthly Room Rent (AC 2-sharing)', 'amount': Decimal('10000.00'), 'order': 1},
            )
            InvoiceLineItem.objects.get_or_create(
                invoice=inv1,
                line_type=InvoiceLineItem.LineType.DISCOUNT,
                tenant_id=tenant.id,
                defaults={'label': 'Loyalty Discount', 'amount': Decimal('-500.00'), 'order': 2},
            )

            # Payment for Inv 1
            Payment.objects.get_or_create(
                invoice=inv1,
                tenant_id=tenant.id,
                defaults={
                    'amount': Decimal('9500.00'),
                    'payment_date': period_start + timedelta(days=1),
                    'payment_mode': Payment.Mode.UPI,
                    'reference': 'UPI/309201940192',
                    'recorded_by': manager,
                },
            )
            inv1.recompute_status()

            # Invoice 2 (Priya Patel) - Partially Paid
            inv2, _ = Invoice.objects.get_or_create(
                resident=res2,
                period_start=period_start,
                tenant_id=tenant.id,
                defaults={
                    'period_end': period_end,
                    'billing_mode': Admission.BillingMode.MONTHLY,
                    'issue_date': period_start,
                    'due_date': due_date,
                    'status': Invoice.Status.ISSUED,
                    'notes': 'Monthly rent for current period',
                    'created_by': owner,
                },
            )
            InvoiceLineItem.objects.get_or_create(
                invoice=inv2,
                line_type=InvoiceLineItem.LineType.ACCOMMODATION,
                tenant_id=tenant.id,
                defaults={'label': 'Monthly Room Rent (AC 2-sharing with food)', 'amount': Decimal('12000.00'), 'order': 1},
            )
            Payment.objects.get_or_create(
                invoice=inv2,
                tenant_id=tenant.id,
                defaults={
                    'amount': Decimal('6000.00'),
                    'payment_date': period_start + timedelta(days=2),
                    'payment_mode': Payment.Mode.CASH,
                    'reference': 'Partial Cash Payment',
                    'recorded_by': manager,
                },
            )
            inv2.recompute_status()

            # Invoice 3 (Amit Kumar) - Issued/Overdue
            inv3, _ = Invoice.objects.get_or_create(
                resident=res3,
                period_start=period_start,
                tenant_id=tenant.id,
                defaults={
                    'period_end': period_end,
                    'billing_mode': Admission.BillingMode.MONTHLY,
                    'issue_date': period_start,
                    'due_date': due_date,
                    'status': Invoice.Status.ISSUED,
                    'notes': 'Monthly rent for current period',
                    'created_by': manager,
                },
            )
            InvoiceLineItem.objects.get_or_create(
                invoice=inv3,
                line_type=InvoiceLineItem.LineType.ACCOMMODATION,
                tenant_id=tenant.id,
                defaults={'label': 'Monthly Room Rent (AC 2-sharing without food)', 'amount': Decimal('8500.00'), 'order': 1},
            )
            inv3.recompute_status()
            self.stdout.write('  [Financials] Created discounts, invoices (Paid, Partially Paid, Issued), line items, and payments.')

            # 6. Operations (Complaints & Visitors)
            comp1, _ = Complaint.objects.get_or_create(
                resident=res1,
                category=Complaint.Category.ELECTRICAL,
                description='Air conditioner in room 101 is leaking water.',
                tenant_id=tenant.id,
                defaults={
                    'priority': Complaint.Priority.HIGH,
                    'status': Complaint.Status.IN_PROGRESS,
                    'assigned_to': manager,
                    'raised_by': owner,
                },
            )
            ComplaintComment.objects.get_or_create(
                complaint=comp1,
                author=manager,
                body='Electrician assigned. Visiting today at 4:00 PM.',
                tenant_id=tenant.id,
            )

            comp2, _ = Complaint.objects.get_or_create(
                resident=res2,
                category=Complaint.Category.INTERNET_WIFI,
                description='WiFi signal is very weak on ground floor room G01.',
                tenant_id=tenant.id,
                defaults={
                    'priority': Complaint.Priority.MEDIUM,
                    'status': Complaint.Status.OPEN,
                    'raised_by': owner,
                },
            )
            self.stdout.write('  [Complaints] Created 2 complaints (AC leakage, WiFi signal).')

            # Visitors
            now = timezone.now()
            Visitor.objects.get_or_create(
                resident=res1,
                visitor_name='Vikram Sharma',
                mobile_number='9123456789',
                tenant_id=tenant.id,
                defaults={
                    'purpose': 'Family Visit',
                    'entry_time': now - timedelta(hours=4),
                    'exit_time': now - timedelta(hours=2),
                    'logged_by': receptionist,
                    'checked_out_by': receptionist,
                },
            )
            Visitor.objects.get_or_create(
                resident=res2,
                visitor_name='Ananya Patel',
                mobile_number='9123456788',
                tenant_id=tenant.id,
                defaults={
                    'purpose': 'Friend Visit',
                    'entry_time': now - timedelta(hours=1),
                    'logged_by': receptionist,
                },
            )
            self.stdout.write('  [Visitors] Created 2 visitor records.')

        self.stdout.write(self.style.SUCCESS('Successfully completed idempotent data seeding!'))
