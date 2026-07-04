from django.contrib import admin

from .models import Complaint, ComplaintComment, Visitor


class ComplaintCommentInline(admin.TabularInline):
    model = ComplaintComment
    extra = 0


@admin.register(Complaint)
class ComplaintAdmin(admin.ModelAdmin):
    inlines = [ComplaintCommentInline]


@admin.register(Visitor)
class VisitorAdmin(admin.ModelAdmin):
    list_display = ['visitor_name', 'resident', 'entry_time', 'exit_time']
