from django.contrib import admin

from .models import (
    AbscondedRecord,
    Admission,
    Allocation,
    BlacklistEntry,
    Resident,
    Transfer,
    Vacate,
)

admin.site.register(Resident)
admin.site.register(Admission)
admin.site.register(Allocation)
admin.site.register(Transfer)
admin.site.register(Vacate)
admin.site.register(AbscondedRecord)
admin.site.register(BlacklistEntry)
