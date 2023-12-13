#!/usr/bin/env python
# -*- encoding: utf-8 -*-
'''
@author  :   Charles Lai
@file    :   models.py
@time    :   2023/04/18 19:24
@contact :   qqing_lai@hotmail.com
'''

# here put the import lib

from django.db import models

from dbapp.model.model_ucenter import UserProfile

from common.extends.models import TimeAbstract
from common.variables import DASHBOARD_TYPE


class DashBoard(TimeAbstract):
    name = models.CharField(max_length=128, unique=True, verbose_name='名称')
    config = models.JSONField(default=list, verbose_name='配置')
    type = models.CharField(max_length=16, choices=DASHBOARD_TYPE, default='index',
                            verbose_name='报表类型', help_text=f"报表类型: {dict(DASHBOARD_TYPE)}")
    creator = models.ForeignKey(
        UserProfile, on_delete=models.CASCADE, verbose_name='创建人')

    def __str__(self):
        return self.name

    class Meta:
        db_table = 'dashboard_dashboard'
        default_permissions = ()
        verbose_name = '报表配置'
        verbose_name_plural = verbose_name + '管理'
