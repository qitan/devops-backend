#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
@Author : Charles Lai
@Contact : qqing_lai@hotmail.com
@Time : 2021/05/13 下午3:44
@FileName: serializer_assets
@Blog : https://imaojia.com
"""
from dbapp.models import *

from common.extends.serializers import ModelSerializer


class IdcSerializers(ModelSerializer):
    class Meta:
        model = Idc
        fields = '__all__'


class IdcListSerializers(ModelSerializer):
    class Meta:
        model = Idc
        fields = ('name', 'alias', 'type', 'supplier', 'desc')
