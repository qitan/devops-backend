#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
@Author : Charles Lai
@Contact : qqing_lai@hotmail.com
@Time : 2021/05/13 下午1:53
@FileName: urls
@Blog : https://imaojia.com
"""

from django.conf.urls import url, include
from django.urls import path
from rest_framework import viewsets
from rest_framework.routers import DefaultRouter
from rest_framework_nested import routers
from cmdb.view.view_cmdb import ProjectConfigViewSet

from cmdb.views import IdcViewSet, \
     ProductViewSet, \
    EnvironmentViewSet, KubernetesClusterViewSet, \
    ProjectViewSet, MicroAppViewSet, AppInfoViewSet, DevLanguageViewSet, \
    RegionViewSet

router = DefaultRouter()

router.register('product', ProductViewSet)
router.register('region', RegionViewSet)
router.register('environment', EnvironmentViewSet)
router.register('asset/idc', IdcViewSet)
router.register('app/language', DevLanguageViewSet)
router.register('app/service', AppInfoViewSet)
router.register('app', MicroAppViewSet)
router.register('project/config', ProjectConfigViewSet)
router.register('project', ProjectViewSet)
router.register('kubernetes', KubernetesClusterViewSet)

router.register('cmdb', viewsets.ViewSet, basename='cmdb')
cmdb_router = routers.NestedDefaultRouter(router, r'cmdb', lookup='table')

urlpatterns = [
    path(r'', include(router.urls)),
    path(r'', include(cmdb_router.urls)),
]
