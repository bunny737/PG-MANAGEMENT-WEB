from django.contrib import admin

from .models import Admission, Resident

admin.site.register(Resident)
admin.site.register(Admission)
