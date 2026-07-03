from django.contrib import admin

from .models import Bed, Floor, Property, PropertyStaffAssignment, Room

admin.site.register(Property)
admin.site.register(Floor)
admin.site.register(Room)
admin.site.register(Bed)
admin.site.register(PropertyStaffAssignment)
