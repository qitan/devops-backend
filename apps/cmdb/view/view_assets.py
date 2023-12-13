#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
@Author : Charles Lai
@Contact : qqing_lai@hotmail.com
@Time : 2021/05/13 下午4:03
@FileName: view_assets
@Blog : https://imaojia.com
"""

from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework import status
from rest_framework import pagination
from rest_framework.filters import SearchFilter, OrderingFilter

import django_filters

from dbapp.models import *
from dbapp.model.model_ucenter import Menu, SystemConfig
from cmdb.serializers import IdcSerializers

from common.extends.viewsets import CustomModelViewSet
from common.extends.filters import CustomSearchFilter


class IdcViewSet(CustomModelViewSet):
    """
    IT资产 - IDC视图

    ### IDC权限
        {'*': ('itasset_all', 'IT资产管理')},
        {'get': ('itasset_list', '查看IT资产')},
        {'post': ('itasset_create', '创建IT资产')},
        {'put': ('itasset_edit', '编辑IT资产')},
        {'delete': ('itasset_delete', '删除IT资产')}
    """
    perms_map = (
        {'*': ('admin', '管理员')},
        {'*': ('itasset_all', 'IT资产管理')},
        {'get': ('itasset_list', '查看IT资产')},
        {'post': ('itasset_create', '创建IT资产')},
        {'put': ('itasset_edit', '编辑IT资产')},
        {'delete': ('itasset_delete', '删除IT资产')}
    )
    queryset = Idc.objects.all()
    serializer_class = IdcSerializers
    filter_backends = (django_filters.rest_framework.DjangoFilterBackend,
                       CustomSearchFilter, OrderingFilter)
    filter_fields = ('name', 'alias', 'forward', 'supplier')
    search_fields = ('name', 'alias', 'ops', 'desc')

    @action(methods=['GET'], url_path='repo', detail=False)
    def get_harbor_repo(self, request):
        harbors = SystemConfig.objects.filter(type='cicd-harbor', status=True)
        return Response({'code': 20000, 'data': [{'id': i.id, 'name': i.name} for i in harbors]})
