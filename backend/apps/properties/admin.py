from django.contrib import admin

from .models import Bed, Building, Floor, Property, PropertySettings, PropertyStaffAssignment, Room

admin.site.register(Property)
admin.site.register(Building)
admin.site.register(Floor)
admin.site.register(Room)
admin.site.register(Bed)
admin.site.register(PropertyStaffAssignment)
admin.site.register(PropertySettings)
