#!/usr/bin/env python
# -*- encoding: utf-8 -*-
'''
@author  :   Charles Lai
@file    :   urls.py
@time    :   2023/04/18 19:26
@contact :   qqing_lai@hotmail.com
'''

# here put the import lib
from django.conf.urls import url, include
from django.urls import path
from rest_framework.routers import DefaultRouter

from dashboard.views import DashBoardViewSet

router = DefaultRouter()

router.register('dashboard', DashBoardViewSet, basename='dashboard')

urlpatterns = [
    path(r'', include(router.urls)),
]
