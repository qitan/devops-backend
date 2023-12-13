#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
@Author : Charles Lai
@Contact : qqing_lai@hotmail.com
@Time : 2020/9/15 下午3:50
@FileName: models.py
@Blog ：https://imaojia.com
"""

from django.db import models
from django.contrib.auth.models import AbstractUser

from common.extends.models import CreateTimeAbstract, TimeAbstract, CommonParent
from common.extends.fernet import EncryptedJsonField
from common.variables import DASHBOARD_TYPE

from fernet_fields import EncryptedTextField


class DataDict(CommonParent):
    key = models.CharField(max_length=80, unique=True, verbose_name='键')
    value = models.CharField(max_length=80, verbose_name='值')
    extra = models.TextField(null=True, blank=True,
                             default='', verbose_name='额外参数')
    desc = models.CharField(max_length=255, blank=True,
                            null=True, verbose_name='备注')

    def __str__(self):
        return self.value

    class Meta:
        db_table = 'ucenter_datadict'
        default_permissions = ()
        verbose_name = '字典'
        verbose_name_plural = verbose_name + '管理'


class Menu(TimeAbstract, CommonParent):
    """
    菜单模型
    """
    name = models.CharField(max_length=30, unique=True, verbose_name="菜单名")
    path = models.CharField(max_length=158, null=True,
                            blank=True, verbose_name="路由地址")
    redirect = models.CharField(
        max_length=200, null=True, blank=True, verbose_name='跳转地址')
    is_frame = models.BooleanField(default=False, verbose_name="外部菜单")
    hidden = models.BooleanField(default=False, verbose_name="是否隐藏")
    spread = models.BooleanField(default=False, verbose_name="是否默认展开")
    sort = models.IntegerField(default=0, verbose_name="排序标记")
    component = models.CharField(
        max_length=200, default='Layout', verbose_name="组件")
    title = models.CharField(max_length=30, null=True,
                             blank=True, verbose_name="菜单显示名")
    icon = models.CharField(max_length=50, null=True,
                            blank=True, verbose_name="图标")
    affix = models.BooleanField(default=False, verbose_name='固定标签')
    single = models.BooleanField(default=False, verbose_name='标签单开')
    activeMenu = models.CharField(
        max_length=128, blank=True, null=True, verbose_name='激活菜单')

    def __str__(self):
        return self.name

    class Meta:
        db_table = 'ucenter_menu'
        default_permissions = ()
        verbose_name = '菜单'
        verbose_name_plural = verbose_name
        ordering = ['sort', 'name']


class Permission(TimeAbstract, CommonParent):
    """
    权限模型
    """
    name = models.CharField(max_length=30, unique=True, verbose_name="权限名")
    method = models.CharField(max_length=50, null=True,
                              blank=True, verbose_name="方法")

    def __str__(self):
        return self.name

    class Meta:
        db_table = 'ucenter_permission'
        default_permissions = ()
        verbose_name = '权限'
        verbose_name_plural = verbose_name
        ordering = ['id', 'name']


class Role(TimeAbstract):
    """
    角色模型
    """
    name = models.CharField(max_length=32, unique=True, verbose_name="角色")
    permissions = models.ManyToManyField(
        "Permission", blank=True, related_name='role_permission', verbose_name="权限")
    menus = models.ManyToManyField("Menu", blank=True, verbose_name="菜单")
    desc = models.CharField(max_length=50, blank=True,
                            null=True, verbose_name="描述")

    def __str__(self):
        return self.name

    class Meta:
        db_table = 'ucenter_role'
        default_permissions = ()
        verbose_name = '角色'
        verbose_name_plural = verbose_name


class Organization(TimeAbstract, CommonParent):
    """
    组织架构
    """
    organization_type_choices = (
        ("company", "公司"),
        ("department", "部门")
    )
    dept_id = models.CharField(
        max_length=32, unique=True, null=True, blank=True, verbose_name='部门ID')
    name = models.CharField(max_length=60, verbose_name="名称")
    leader_user_id = models.CharField(
        max_length=64, null=True, blank=True, verbose_name="部门领导ID")
    type = models.CharField(
        max_length=20, choices=organization_type_choices, default="company", verbose_name="类型")
    dn = models.CharField(max_length=120, null=True,
                          blank=True, unique=True, verbose_name="ldap dn")

    @property
    def full(self):
        l = []
        self.get_parents(l)
        return l

    def get_parents(self, parent_result: list):
        if not parent_result:
            parent_result.append(self)
        parent_obj = self.parent
        if parent_obj:
            parent_result.append(parent_obj)
            parent_obj.get_parents(parent_result)

    def __str__(self):
        return self.name

    class ExtMeta:
        related = True
        dashboard = False

    class Meta:
        db_table = 'ucenter_organization'
        default_permissions = ()
        verbose_name = "组织架构"
        verbose_name_plural = verbose_name


class UserProfile(TimeAbstract, AbstractUser):
    """
    用户信息
    """
    mobile = models.CharField(max_length=11, null=True,
                              blank=True, verbose_name="手机号码")
    avatar = models.ImageField(upload_to="static/%Y/%m", default="image/default.png",
                               max_length=250, null=True, blank=True)
    department = models.ManyToManyField(
        Organization, related_name='org_user', verbose_name='部门')
    position = models.CharField(
        max_length=50, null=True, blank=True, verbose_name="职能")
    title = models.CharField(max_length=50, null=True,
                             blank=True, verbose_name="职位")
    leader_user_id = models.CharField(
        max_length=64, null=True, blank=True, verbose_name="直属领导ID")
    roles = models.ManyToManyField(
        "Role", verbose_name="角色", related_name='user_role', blank=True)
    dn = models.CharField(max_length=120, null=True,
                          blank=True, unique=True, verbose_name="ldap dn")
    is_ldap = models.BooleanField(default=False, verbose_name="是否ldap用户")
    ding_userid = models.CharField(
        max_length=150, null=True, blank=True, verbose_name="钉钉用户ID")
    feishu_userid = models.CharField(
        max_length=120, null=True, blank=True, verbose_name="飞书UserID")
    feishu_unionid = models.CharField(
        max_length=120, null=True, blank=True, verbose_name='飞书UnionID')
    feishu_openid = models.CharField(
        max_length=120, null=True, blank=True, verbose_name='飞书OpenID')

    @property
    def name(self):
        if self.first_name:
            return self.first_name
        if self.last_name:
            return self.last_name
        return self.username

    def __str__(self):
        return self.name

    class ExtMeta:
        related = True
        dashboard = False
        icon = 'peoples'

    class Meta:
        db_table = 'ucenter_userprofile'
        default_permissions = ()
        verbose_name = "用户信息"
        verbose_name_plural = verbose_name
        ordering = ['id']


class AuditLog(CreateTimeAbstract):
    user = models.CharField(max_length=244, verbose_name='用户')
    type = models.CharField(max_length=64, verbose_name='类型')
    action = models.CharField(max_length=20, verbose_name='动作')
    action_ip = models.CharField(max_length=15, verbose_name='来源IP')
    content = models.TextField(default='', verbose_name='内容')
    data = models.TextField(null=True, blank=True,
                            default='', verbose_name='更新后的数据')
    old_data = models.TextField(
        null=True, blank=True, default='', verbose_name='更新前的数据')

    class Meta:
        db_table = 'ucenter_auditlog'
        default_permissions = ()
        ordering = ['-created_time']
        verbose_name = '审计信息'
        verbose_name_plural = '审计信息管理'


class SystemConfig(TimeAbstract):
    name = models.CharField(max_length=64, default='',
                            unique=True, verbose_name='名称')
    config = EncryptedJsonField(default=dict, verbose_name='配置')
    status = models.BooleanField(default=False, verbose_name='启用')
    type = models.CharField(max_length=64, default='', verbose_name='类型')

    def __str__(self):
        return self.name

    class Meta:
        db_table = 'ucenter_systemconfig'
        default_permissions = ()
        verbose_name = '系统设置'
        verbose_name_plural = verbose_name + '管理'
