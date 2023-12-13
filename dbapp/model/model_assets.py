#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
@Author : Charles Lai
@Contact : qqing_lai@hotmail.com
@Time : 2021/05/13 上午11:22
@FileName: model_assets.py
@Blog ： https://imaojia.com
"""

from django.contrib.auth.models import User
from django.db import models

from dbapp.model.model_ucenter import UserProfile

from common.extends.fernet import EncryptedJsonField
from common.extends.models import TimeAbstract, CreateTimeAbstract
from common.extends.storage import FileUploadStorage
from common.variables import *

from config import UPLOAD_PATH, UPLOAD_ROOT


class FileUpload(TimeAbstract):
    name = models.CharField(max_length=250, default='', verbose_name='文件名')
    file = models.FileField(upload_to=UPLOAD_PATH, storage=FileUploadStorage(
        upload_root=UPLOAD_ROOT), default=None)
    md5 = models.CharField(max_length=250)
    table = models.CharField(max_length=64, default='', verbose_name='关联表')
    uploader = models.ForeignKey(
        UserProfile, null=True, blank=True, on_delete=models.SET_NULL, verbose_name='上传者')
    # 0: 未处理, 1: 已处理
    status = models.SmallIntegerField(default=0, verbose_name='状态')

    def __str__(self):
        return self.name

    class Meta:
        db_table = 'cmdb_fileupload'
        default_permissions = ()
        verbose_name = '文件上传'
        verbose_name_plural = verbose_name + '管理'


class Region(TimeAbstract):
    name = models.CharField(max_length=100, unique=True, verbose_name='地域')
    alias = models.CharField(max_length=128, default='', verbose_name='地域别名')
    desc = models.TextField(verbose_name='详情描述', null=True, blank=True)
    extra = models.JSONField(default=dict, verbose_name='扩展字段')
    # {0: 禁用， 1： 启用}
    is_enable = models.SmallIntegerField(
        default=1, verbose_name='启用', help_text='状态 {0: 禁用， 1： 启用}，默认值为1')

    def __str__(self) -> str:
        return self.alias

    class ExtMeta:
        related = True
        dashboard = True

    class Meta:
        db_table = 'cmdb_region'
        verbose_name = '地域'
        verbose_name_plural = verbose_name + '管理'


class Idc(TimeAbstract):
    """
    Idc模型
    """
    name = models.CharField(max_length=100, unique=True, verbose_name='名称')
    alias = models.CharField(max_length=128, unique=True, verbose_name='别名')
    region = models.ForeignKey(
        Region, blank=True, null=True, on_delete=models.PROTECT, verbose_name='区域')
    type = models.SmallIntegerField(default=0, choices=IDC_TYPE, verbose_name='机房类型',
                                    help_text=f"可选： {IDC_TYPE}")
    supplier = models.CharField(
        max_length=128, default=None, null=True, blank=True, verbose_name='服务商')
    config = EncryptedJsonField(default=dict, verbose_name='配置信息',
                                help_text='阿里云：{"key":"key","secret":"secret","region":["cn-south-1"],"project":[]}\n华为云：{"domain":"domain","user":"user","password":password","project":[{"region":"region","project_id":"project_id"}]}')
    forward = models.BooleanField(default=False, verbose_name='是否中转')
    ops = models.CharField(max_length=100, blank=True,
                           null=True, verbose_name='运维机器')
    repo = models.SmallIntegerField(default=0, verbose_name='镜像仓库')
    contact = models.JSONField(default=list, verbose_name='联系人')
    desc = models.TextField(default='', null=True,
                            blank=True, verbose_name='备注')

    def __str__(self):
        return self.name

    class ExtMeta:
        related = True
        dashboard = True
        icon = 'international'

    class Meta:
        db_table = 'cmdb_idc'
        verbose_name = 'IDC机房'
        verbose_name_plural = verbose_name + '管理'
