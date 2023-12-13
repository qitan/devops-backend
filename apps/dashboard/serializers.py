#!/usr/bin/env python
# -*- encoding: utf-8 -*-
'''
@author  :   Charles Lai
@file    :   serializers.py
@time    :   2023/04/18 19:25
@contact :   qqing_lai@hotmail.com
'''

# here put the import lib
from dbapp.model.model_dashboard import DashBoard

from common.extends.serializers import ModelSerializer


class DashBoardSerializers(ModelSerializer):

    class Meta:
        model = DashBoard
        fields = '__all__'
        read_only_fields = ('creator', )
