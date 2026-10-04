from django.contrib import admin

from .models import Complaint, ComplaintComment, Visitor


class ComplaintCommentInline(admin.TabularInline):
    model = ComplaintComment
    extra = 0


@admin.register(Complaint)
class ComplaintAdmin(admin.ModelAdmin):
    list_display = ['resident', 'category', 'priority', 'status', 'created_at']
    list_filter = ['status', 'priority', 'category']
    search_fields = ['description', 'resident__first_name', 'resident__last_name']
    inlines = [ComplaintCommentInline]


@admin.register(ComplaintComment)
class ComplaintCommentAdmin(admin.ModelAdmin):
    list_display = ['complaint', 'author', 'created_at']
    search_fields = ['body', 'complaint__description']


@admin.register(Visitor)
class VisitorAdmin(admin.ModelAdmin):
    list_display = ['visitor_name', 'resident', 'entry_time', 'exit_time']
    search_fields = ['visitor_name', 'resident__first_name', 'resident__last_name']
