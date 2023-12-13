#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
@Author : Charles Lai
@Contact : qqing_lai@hotmail.com
@Time : 2020/12/31 下午3:29
@FileName: models.py
@Blog ：https://imaojia.com
"""

from django.db import models


class CommonParent(models.Model):
    parent = models.ForeignKey("self", null=True, blank=True, on_delete=models.SET_NULL, related_name='children')

    class Meta:
        abstract = True


class TimeAbstract(models.Model):
    update_time = models.DateTimeField(auto_now=True, null=True, blank=True, verbose_name='更新时间')
    created_time = models.DateTimeField(auto_now_add=True, null=True, blank=True, verbose_name='创建时间')

    class ExtMeta:
        related = False
        dashboard = False

    class Meta:
        abstract = True
        ordering = ['-id']


class CreateTimeAbstract(models.Model):
    created_time = models.DateTimeField(auto_now_add=True, null=True, blank=True, verbose_name='创建时间')

    class ExtMeta:
        related = False
        dashboard = False

    class Meta:
        abstract = True


class JobManager(models.Manager):
    def __init__(self, defer_fields=None):
        self.defer_fields = defer_fields
        super().__init__()

    def get_queryset(self):
        if self.defer_fields:
            return super().get_queryset().defer(*self.defer_fields)
        return super().get_queryset()
