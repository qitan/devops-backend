from django.contrib import admin
from dbapp.models import Idc, Environment

# Register your models here.
admin.site.register([Idc, Environment])
