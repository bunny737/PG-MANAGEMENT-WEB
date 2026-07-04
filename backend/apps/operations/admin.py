from django.contrib import admin

from .models import Complaint, ComplaintComment


class ComplaintCommentInline(admin.TabularInline):
    model = ComplaintComment
    extra = 0


@admin.register(Complaint)
class ComplaintAdmin(admin.ModelAdmin):
    inlines = [ComplaintCommentInline]
