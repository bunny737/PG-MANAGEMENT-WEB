from django.contrib import admin

from .models import Admission, Allocation, Resident, Transfer

admin.site.register(Resident)
admin.site.register(Admission)
admin.site.register(Allocation)
admin.site.register(Transfer)
