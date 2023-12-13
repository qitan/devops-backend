#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
@Author : Charles Lai
@Contact : qqing_lai@hotmail.com
@Time : 2020/9/15 下午7:48
@FileName: views.py
@Blog ：https://imaojia.com
"""

from django.apps import apps
from cmdb.view import *
from cmdb.serializers import *
from common.extends.filters import CustomFilter
from common.extends.viewsets import CustomModelViewSet
from common.md5 import md5
from config import MEDIA_ROOT
import logging
from drf_yasg.utils import swagger_auto_schema

logger = logging.getLogger('drf')


class FileUploadViewSet(CustomModelViewSet):
    perms_map = ()
    queryset = FileUpload.objects.all()
    serializer_class = FileUploadSerializers

    def create(self, request, *args, **kwargs):
        file_obj = request.data.get('name')
        _file_md5 = md5(file_obj)
        asset_type = request.data.get('type')
        platform = request.data.get('platform')
        try:
            FileUpload.objects.get(md5=_file_md5)
            return Response({'code': 20000, 'status': 'failed', 'message': '文件已存在'})
        except BaseException as e:
            pass
        request.data['md5'] = _file_md5
        serializer = self.get_serializer(data=request.data)
        if not serializer.is_valid():
            return Response({'code': 40000, 'status': 'failed', 'message': serializer.errors})
        try:
            self.perform_create(serializer)
        except BaseException as e:
            return Response({'code': 50000, 'status': 'failed', 'message': str(e)})
        data = serializer.data
        data['status'] = 'success'
        data['code'] = 20000
        return Response(data)
