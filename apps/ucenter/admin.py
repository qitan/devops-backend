from django.contrib import admin

# Register your models here.
from dbapp.models import UserProfile


class UserProfileAdmin(admin.ModelAdmin):
    def save_model(self, request, obj, form, change):
        obj.set_password(obj.password)
        super().save_model(request, obj, form, change)


admin.site.register(UserProfile, UserProfileAdmin)

admin.site.site_title = 'DevOps平台'
admin.site.site_header = 'DevOps平台管理'
