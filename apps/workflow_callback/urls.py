#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
@Author : Ken Chen
@Contact : chenxiaoshun@yl-scm.com
@Time : 2021/12/10 下午1:53
@FileName: urls
"""

from django.conf.urls import url, include
from rest_framework.routers import DefaultRouter

from workflow_callback.views.app import AppMemberAPIView

router = DefaultRouter()

urlpatterns = [
    url(r'', include(router.urls)),
    url(r'app/member', AppMemberAPIView.as_view(), name='app-member'),
]
