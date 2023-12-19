#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
@Author : Charles Lai
@Contact : qqing_lai@hotmail.com
@Time : 2020/9/15 下午4:08
@FileName: views.py
@Blog ：https://imaojia.com
"""
import hashlib
from django.core.cache import cache
from rest_framework import viewsets, status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.decorators import action
from rest_framework import pagination
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView
from rest_framework_simplejwt.exceptions import TokenError, InvalidToken
from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.tokens import RefreshToken, Token, OutstandingToken
from rest_framework.filters import SearchFilter, OrderingFilter

import django_filters

from django_q.tasks import async_task, result
from django.contrib.auth.models import update_last_login
from django.db.models import Q
from django.contrib.auth import logout
from common.variables import FEISHU_SYNC_USER_JOB_CACHE_KEY
from dbapp.models import Menu, Permission, Role, Organization, UserProfile, AuditLog, SystemConfig, DataDict
from ucenter.serializers import MenuSerializers, MenuListSerializers, PermissionListSerializers, PermissionSerializers, \
    RoleListSerializers, \
    RoleSerializers, OrganizationSerializers, \
    UserProfileListSerializers, UserProfileSerializers, UserProfileDetailSerializers, AuditLogSerializers, \
    AuditLogActivitySerializers, SystemConfigSerializers, \
    SystemConfigListSerializers, DataDictSerializers

from common.extends.viewsets import CustomModelViewSet, CustomModelParentViewSet
from common.extends.permissions import RbacPermission
from common.extends.JwtAuth import CustomInvalidToken, TokenObtainPairSerializer, TokenRefreshSerializer
from common.extends.handler import log_audit
from common.extends.filters import AuditLogFilter, CustomSearchFilter

from common.utils.JenkinsAPI import GlueJenkins
from common.get_ip import user_ip
from common.ext_fun import ThirdPartyUser, set_redis_data, get_redis_data, timeline_generate, time_period, \
    node_filter
from qtasks.tasks import test_notify
from django.conf import settings
from django.contrib.auth import login, REDIRECT_FIELD_NAME
from django.views.decorators.csrf import csrf_exempt, csrf_protect
from django.views.decorators.cache import never_cache

import datetime
import time
import shortuuid
import json
import logging

logger = logging.getLogger('drf')

DEFAULT_SESSION_TIMEOUT = None


class DataDictViewSet(CustomModelParentViewSet):
    """
    数据字典视图

    ### 数据字典权限
        {'*': ('data_all', '数据字典管理')},
        {'get': ('data_list', '查看数据字典')},
        {'post': ('data_create', '创建数据字典')},
        {'put': ('data_edit', '编辑数据字典')},
        {'patch': ('data_edit', '编辑数据字典')},
        {'delete': ('data_delete', '删除数据字典')}
    """
    perms_map = (
        {'*': ('admin', '管理员')},
        {'*': ('data_all', '数据字典管理')},
        {'get': ('data_list', '查看数据字典')},
        {'post': ('data_create', '创建数据字典')},
        {'put': ('data_edit', '编辑数据字典')},
        {'patch': ('data_edit', '编辑数据字典')},
        {'delete': ('data_delete', '删除数据字典')}
    )
    queryset = DataDict.objects.all()
    serializer_class = DataDictSerializers
    filter_backends = (
        django_filters.rest_framework.DjangoFilterBackend, SearchFilter, OrderingFilter)
    filter_fields = ('key', 'value')
    search_fields = ('key', 'value')

    def perform_update(self, serializer):
        serializer.save()
        cache.delete(f"datadict:{serializer.data['key']}:0")
        cache.delete(f"datadict:{serializer.data['key']}:1")

    @action(methods=['GET'], url_path='user', detail=False)
    def get_user(self, request):
        """
        获取用户列表

        ### 传递参数
            force: 0|1
            force为1时强制刷新
        """
        _force = request.query_params.get('force', None)
        position = request.query_params.get('position', None)
        _key = str(
            f'project:users:{self.request.user.id}-{self.request.query_params}')
        try:
            data = cache.get(_key)
        except BaseException as e:
            cache.delete(_key)
            data = None
        if not data or _force:
            if position:
                users = UserProfile.objects.exclude(
                    username='thirdparty').filter(position=position)
            else:
                users = UserProfile.objects.exclude(username='thirdparty')
            data = [{'id': i.id, 'first_name': i.first_name, 'username': i.username, 'name': i.name, 'title': i.title,
                     'position': i.position} for i in users]
            cache.set(_key, data, timeout=60 * 60 * 24)
        return Response({'code': 20000, 'data': data})

    @action(methods=['GET'], url_path='extra', detail=False)
    def get_by_key(self, request):
        """
        通过指定key名获取

        参数: key
        """
        key_name = request.query_params.get('key', None)
        instance = self.queryset.get(key=key_name)
        serializer = self.get_serializer(instance)
        data = {'data': serializer.data, 'code': 20000, 'status': 'success'}
        return Response(data)


class AuditLogViewSet(CustomModelViewSet):
    """
    审计日志视图

    ### 审计日志权限
        {'get': ('audit_list', '查看审计日志')}
    """
    perms_map = (
        {'*': ('admin', '管理员')},
        {'get': ('audit_list', '查看审计日志')}
    )
    queryset = AuditLog.objects.all()
    serializer_class = AuditLogSerializers
    filter_backends = (django_filters.rest_framework.DjangoFilterBackend,
                       CustomSearchFilter, OrderingFilter)
    filter_class = AuditLogFilter
    filter_fields = ('user', 'type', 'action', 'action_ip', 'operator')
    search_fields = ('user', 'type', 'action', 'action_ip', 'content')

    def create(self, request, *args, **kwargs):
        pass

    def update(self, request, *args, **kwargs):
        pass

    def destroy(self, request, *args, **kwargs):
        pass


class MenuViewSet(CustomModelParentViewSet):
    """
    菜单视图

    ### 菜单权限
        {'*': ('menu_all', '菜单管理')},
        {'get': ('menu_list', '查看菜单')},
        {'post': ('menu_create', '创建菜单')},
        {'put': ('menu_edit', '编辑菜单')},
        {'patch': ('menu_edit', '编辑菜单')},
        {'delete': ('menu_delete', '删除菜单')}
    """
    perms_map = (
        {'*': ('admin', '管理员')},
        {'*': ('menu_all', '菜单管理')},
        {'get': ('menu_list', '查看菜单')},
        {'post': ('menu_create', '创建菜单')},
        {'put': ('menu_edit', '编辑菜单')},
        {'patch': ('menu_edit', '编辑菜单')},
        {'delete': ('menu_delete', '删除菜单')}
    )
    queryset = Menu.objects.all()
    serializer_class = MenuSerializers

    def get_serializer_class(self):
        if self.action in ['list', 'retrieve']:
            return MenuListSerializers
        return MenuSerializers


class PermissionViewSet(CustomModelParentViewSet):
    """
    权限视图

    ### 查看权限列表的权限
        {'*': ('perm_all', '权限管理')},
        {'get': ('perm_list', '查看权限')},
    """
    perms_map = (
        {'*': ('admin', '管理员')},
        {'*': ('perm_all', '权限管理')},
        {'get': ('perm_list', '查看权限')}
    )
    queryset = Permission.objects.all()
    serializer_class = PermissionSerializers

    def get_serializer_class(self):
        if self.action in ['list', 'retrieve']:
            return PermissionListSerializers
        return PermissionSerializers


class RoleViewSet(CustomModelViewSet):
    """
    角色视图

    ### 角色管理权限
        {'*': ('role_all', '角色管理')},
        {'get': ('role_list', '查看角色')},
        {'post': ('role_create', '创建角色')},
        {'put': ('role_edit', '编辑角色')},
        {'patch': ('role_edit', '编辑角色')},
        {'delete': ('role_delete', '删除角色')}
    """
    perms_map = (
        {'*': ('admin', '管理员')},
        {'*': ('role_all', '角色管理')},
        {'get': ('role_list', '查看角色')},
        {'post': ('role_create', '创建角色')},
        {'put': ('role_edit', '编辑角色')},
        {'patch': ('role_edit', '编辑角色')},
        {'delete': ('role_delete', '删除角色')}
    )
    queryset = Role.objects.exclude(name='thirdparty')
    serializer_class = RoleSerializers

    def get_serializer_class(self):
        if self.action == 'list' or self.action == 'retrieve':
            return RoleListSerializers
        return RoleSerializers

    def perform_destroy(self, instance):
        if instance.name != '默认角色':
            instance.delete()


class OrganizationViewSet(CustomModelParentViewSet):
    """
    组织架构视图

    ### 组织架构权限
        {'*': ('org_all', '组织架构管理')},
        {'get': ('org_list', '查看组织架构')},
        {'post': ('org_create', '创建组织架构')},
        {'put': ('org_edit', '编辑组织架构')},
        {'patch': ('org_edit', '编辑组织架构')},
        {'delete': ('org_delete', '删除组织架构')}
    """
    perms_map = (
        {'*': ('admin', '管理员')},
        {'*': ('org_all', '组织架构管理')},
        {'get': ('org_list', '查看组织架构')},
        {'post': ('org_create', '创建组织架构')},
        {'put': ('org_edit', '编辑组织架构')},
        {'patch': ('org_edit', '编辑组织架构')},
        {'delete': ('org_delete', '删除组织架构')}
    )
    queryset = Organization.objects.all()
    serializer_class = OrganizationSerializers
    search_fields = ('name', 'dn')

    def get_org_users(self, org):
        qs = org.org_user.all()
        for i in org.children.all():
            qs |= self.get_org_users(i)
        return qs

    @action(methods=['GET'], url_path='users', detail=True)
    def organization_users(self, request, pk=None):
        page_size = request.query_params.get('page_size')
        pagination.PageNumberPagination.page_size = page_size
        qs = self.queryset.get(pk=pk)
        queryset = self.get_org_users(qs).distinct()
        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = UserProfileListSerializers(page, many=True)
            return self.get_paginated_response(serializer.data)
        serializer = UserProfileListSerializers(queryset, many=True)
        data = {'data': {'total': queryset.count(), 'items': serializer.data},
                'code': 20000, 'status': 'success'}
        return Response(data)


class UserViewSet(CustomModelViewSet):
    """
    用户管理视图

    ### 用户管理权限
        {'*': ('user_all', '用户管理')},
        {'get': ('user_list', '查看用户')},
        {'post': ('user_create', '创建用户')},
        {'put': ('user_edit', '编辑用户')},
        {'patch': ('user_edit', '编辑用户')},
        {'delete': ('user_delete', '删除用户')}
    """
    perms_map = (
        {'*': ('admin', '管理员')},
        {'*': ('user_all', '用户管理')},
        {'get': ('user_list', '查看用户')},
        {'post': ('user_create', '创建用户')},
        {'put': ('user_edit', '编辑用户')},
        {'patch': ('user_edit', '编辑用户')},
        {'delete': ('user_delete', '删除用户')}
    )
    queryset = UserProfile.objects.exclude(
        Q(username='thirdparty') | Q(is_active=False))
    serializer_class = UserProfileSerializers
    filter_backends = (
        django_filters.rest_framework.DjangoFilterBackend, SearchFilter, OrderingFilter)
    filter_fields = {
        'position': ['exact'],
        'title': ['exact'],
        'id': ['in', 'exact'],
    }
    search_fields = ('position', 'mobile', 'title',
                     'username', 'first_name', 'email')

    def get_serializer_class(self):
        if self.action == 'list':
            return UserProfileListSerializers
        if self.action == 'detail' or self.action == 'retrieve':
            return UserProfileDetailSerializers
        return UserProfileSerializers

    def create(self, request, *args, **kwargs):
        if self.queryset.filter(username=request.data['username']):
            return Response({'code': 20000, 'message': '%s 账号已存在!' % request.data['username']})
        password = shortuuid.ShortUUID().random(length=8)
        request.data['password'] = password
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        data = serializer.data
        log_audit(request, action_type=self.serializer_class.Meta.model.__name__, action='创建', content='',
                  data=serializer.data)

        data['password'] = password
        data['status'] = 'success'
        data['code'] = 20000

        return Response(data)

    def perform_destroy(self, instance):
        # 禁用用户
        instance.is_active = False
        instance.save()

    @action(methods=['POST'], url_path='password/reset', detail=False)
    def password_reset(self, request):
        """
        重置用户密码

        ### 重置用户密码
        """
        data = self.request.data
        user = self.queryset.get(pk=data['uid'])
        m = hashlib.md5()
        m.update(data['password'])
        password = m.hexdigest()
        user.set_password(password)
        user.save()

        log_audit(request, action_type=self.serializer_class.Meta.model.__name__, action='密码修改',
                  content=f"修改用户{user.first_name or user.username}密码")

        return Response({'code': 20000, 'data': '密码已更新.'})

    @action(methods=['GET'], url_path='detail', detail=False)
    def detail_info(self, request, pk=None, *args, **kwargs):
        """
        用户详细列表

        ### 获取用户详细信息，用户管理模块
        """
        page_size = request.query_params.get('page_size')
        pagination.PageNumberPagination.page_size = page_size
        queryset = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)
        serializer = self.get_serializer(queryset, many=True)
        data = {'data': {'total': queryset.count(), 'items': serializer.data},
                'code': 20000, 'status': 'success'}
        return Response(data)


class UserAuthTokenView(TokenObtainPairView):
    """
    用户登录视图
    """
    perms_map = ()
    serializer_class = TokenObtainPairSerializer

    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        data = None
        try:
            if not serializer.is_valid():
                logger.exception(f'用户登录异常{serializer.errors}')
                return Response({'code': 40108, 'message': str(e.args[0])}, status=status.HTTP_401_UNAUTHORIZED)
            data = serializer.validated_data
            log_audit(request, 'User', '登录成功', '',
                      user=request.data['username'])
            # 用户登录成功,绑定默认角色并更新最后登录时间
            user = UserProfile.objects.get(username=request.data['username'])
            try:
                role = Role.objects.get(name='默认角色')
                user.roles.add(*[role.id])
            except BaseException as e:
                logger.exception(f"绑定用户角色失败, 原因: {e}")
            update_last_login(None, user)
        except BaseException as e:
            logger.error(f"用户登录异常, 原因: {e}")
            log_audit(request, 'User', '登录失败', '',
                      user=request.data['username'])
            return Response({'code': 40108, 'message': str(e.args[0])}, status=status.HTTP_401_UNAUTHORIZED)

        return Response({'code': 20000, 'data': data})


class UserAuthTokenRefreshView(TokenRefreshView):
    """
    用户token刷新视图
    """
    perms_map = ()
    serializer_class = TokenRefreshSerializer

    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)

        try:
            if not serializer.is_valid(raise_exception=False):
                logger.error(f'Token刷新校验不通过: {serializer.errors}')
                return Response({'code': 40101, 'message': '刷新Token已过期，请重新登录.'}, status=status.HTTP_401_UNAUTHORIZED)
            data = serializer.validated_data
            data['username'] = request.user.username
        except TokenError as e:
            logger.error(f"刷新用户token异常, 原因: {e}")
            return Response({'code': 40101, 'message': '刷新Token已过期，请重新登录.'}, status=status.HTTP_401_UNAUTHORIZED)

        return Response({'code': 20000, 'data': data})


class UserLogout(APIView):
    """
    用户注销视图
    """
    perms_map = ()

    def get(self, request, format=None):
        logout(request)
        return Response({
            'code': 20000
        })


class UserProfileViewSet(CustomModelViewSet):
    """
    用户信息视图

    ### 用户信息管理权限
        {'*': ('userinfo_all', '用户信息管理')},
        {'get': ('userinfo_list', '查看用户信息')},
        {'put': ('userinfo_edit', '编辑用户信息')},
        {'patch': ('userinfo_edit', '编辑用户信息')},
    """
    perms_map = (
        {'*': ('admin', '管理员')},
        {'*': ('userinfo_all', '用户信息管理')},
        {'get': ('userinfo_list', '查看用户信息')},
        {'put': ('userinfo_edit', '编辑用户信息')},
        {'patch': ('userinfo_edit', '编辑用户信息')},
    )
    queryset = UserProfile.objects.exclude(username='thirdparty')
    authentication_classes = [JWTAuthentication, ]
    serializer_class = UserProfileDetailSerializers
    filter_backends = (django_filters.rest_framework.DjangoFilterBackend,
                       CustomSearchFilter, OrderingFilter)
    filter_class = AuditLogFilter
    filter_fields = ('user', 'type', 'action', 'action_ip', 'operator')
    search_fields = ('user', 'type', 'action', 'action_ip', 'content')

    def get_serializer_class(self):
        if self.action == 'create' or self.action == 'update':
            return UserProfileSerializers
        if self.action == 'user_activity':
            return AuditLogActivitySerializers
        return UserProfileDetailSerializers

    def update(self, request, *args, **kwargs):
        instance = self.queryset.get(username=request.user)
        instance.__dict__.update(**request.data)
        instance.save()

        log_audit(request, self.serializer_class.Meta.model.__name__, '更新用户信息', '',
                  data=self.serializer_class(instance).data,
                  old_data=self.serializer_class(instance).data)

        data = {'data': '更新成功', 'status': 'success', 'code': 20000}
        return Response(data)

    def menu_sort(self, menus):
        """
        菜单排序
        sort值越小越靠前
        :param menus:
        :return:
        """
        for menu in menus:
            try:
                if menu['children']:
                    self.menu_sort(menu['children'])
            except KeyError:
                pass
        try:
            menus.sort(key=lambda k: (k.get('sort')))
        except:
            pass
        return menus

    @action(methods=['GET'], url_path='info', detail=False)
    def info(self, request):
        """
        获取用户信息
        :param request:
        :return:
        """
        serializer = self.get_serializer(request.user)
        data = serializer.data
        data.pop('password', None)
        data.pop('routers', None)
        data['roles'] = ['超级管理员'] if request.user.is_superuser else [
            i['name'] for i in data['user_roles']]
        return Response({'code': 20000, 'data': data})

    @action(methods=['GET'], url_path='menus', detail=False)
    def menus(self, request):
        """
        获取用户菜单
        :param request:
        :return:
        """
        serializer = self.get_serializer(request.user)
        data = serializer.data
        routers = data['routers']
        routers = self.menu_sort(routers)
        data = {'data': {'routers': routers},
                'code': 20000, 'status': 'success'}
        return Response(data)

    @action(methods=['GET'], url_path='activity', detail=False, queryset=AuditLog.objects.all())
    def user_activity(self, request):
        page_size = request.query_params.get('page_size')
        pagination.PageNumberPagination.page_size = page_size
        queryset = self.filter_queryset(
            self.get_queryset().filter(Q(user=request.user.first_name) | Q(user=request.user.username)))
        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)
        serializer = self.get_serializer(queryset, many=True)
        data = {'data': {'total': queryset.count(), 'items': serializer.data},
                'code': 20000, 'status': 'success'}
        return Response(data)


class SystemConfigViewSet(CustomModelViewSet):
    """
    系统设置视图

    ### 系统设置权限
        {'*': ('system_all', '系统设置管理')},
        {'get': ('system_list', '查看系统设置')},
    """
    perms_map = (
        {'*': ('admin', '管理员')},
        {'*': ('system_all', '系统设置管理')},
        {'get': ('system_list', '查看系统设置')},
    )
    queryset = SystemConfig.objects.all()
    serializer_class = SystemConfigSerializers
    filter_backends = (
        django_filters.rest_framework.DjangoFilterBackend, SearchFilter, OrderingFilter)
    filter_fields = ('name', 'type')
    search_fields = ('name', 'type')

    def get_serializer_class(self):
        if self.action in ['list', 'retrieve']:
            return SystemConfigListSerializers
        return SystemConfigSerializers

    @staticmethod
    def set_credit(jenkins_cli, name, user=None, password=None, secret=None, comment=None):
        try:
            credit = jenkins_cli.credential_exists(name)
            if credit:
                jenkins_cli.reconfig_credential_global(name=name, user=user, password=password, secret=secret,
                                                       comment=comment)
            else:
                jenkins_cli.create_credential_global(name=name, user=user, password=password, secret=secret,
                                                     comment=comment)
        except BaseException as e:
            print('err: ', str(e))

    def create(self, request, *args, **kwargs):
        if request.data['type'] == 'thirdparty':
            # 生成token给第三方访问
            expired_time = self.request.data['config']['expired_time']
            seconds = int(expired_time / 1000 - time.time())
            user = ThirdPartyUser().get_user()
            token = RefreshToken.for_user(user)
            access_token = token.access_token
            # 设置token过期时间
            access_token.set_exp(
                lifetime=(datetime.timedelta(seconds=seconds)))
            request.data['config'] = {
                'expired_time': time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(expired_time / 1000)),
                'token': str(access_token)}
        if request.data['type'] == 'cicd-jenkins':
            jenkins_cli = GlueJenkins(request.data['config']['url'], username=request.data['config']['user'],
                                      password=request.data['config']['password'])
            gitlab = get_redis_data('cicd-gitlab')
            if gitlab is None:
                return Response({'code': 20000, 'status': 'failed', 'message': '请先配置Gitlab信息.'})
            credit = jenkins_cli.create_credential_global(user='oauth2' if gitlab['token'] else gitlab['user'],
                                                          password=gitlab['token'] or gitlab['password'],
                                                          comment='GitLab')
            secret = get_redis_data(
                request.data['config']['platform_secret'])['token']
            platform_credit = jenkins_cli.create_credential_global(
                secret=secret, comment='Platform')
            request.data['config']['gitlab_credit'] = credit['data']
            request.data['config']['platform_credit'] = platform_credit['data']
        if request.data['type'] == 'cicd-harbor':
            jenkins = get_redis_data('cicd-jenkins')
            try:
                comment = f'Harbor {request.data["name"]} at {datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")} by {request.user}'
                jenkins_cli = GlueJenkins(
                    jenkins['url'], username=jenkins['user'], password=jenkins['password'])
                credit = jenkins_cli.create_credential_global(user=self.request.data['config']['user'],
                                                              password=self.request.data['config']['password'],
                                                              comment=comment)
                self.request.data['config']['harbor_credit'] = credit['data']
            except BaseException as e:
                print('create harbor err', e)

        serializer = self.get_serializer(data=request.data)
        if not serializer.is_valid():
            return Response({'code': 40000, 'status': 'failed', 'message': serializer.errors})
        try:
            self.perform_create(serializer)
        except BaseException as e:
            return Response({'code': 50000, 'status': 'failed', 'message': str(e)})
        log_audit(request, action_type=self.serializer_class.Meta.model.__name__, action='创建', content='',
                  data=serializer.data)

        data = {'data': serializer.data, 'status': 'success', 'code': 20000}
        return Response(data)

    def update(self, request, *args, **kwargs):
        partial = kwargs.pop('partial', False)
        filters = {'pk': kwargs['pk']}
        if 'update_time' in self.request.data:
            if self.request.data['update_time']:
                filters['update_time'] = self.request.data['update_time']
        try:
            instance = self.queryset.get(**filters)
        except BaseException as e:
            return Response({'code': 20000, 'data': '请求的资源已被更改或者不存在，请重新获取资源', 'status': 'failed',
                             'message': str(e)})

        if request.data['type'] == 'cicd-gitlab':
            jenkins = get_redis_data('cicd-jenkins')
            try:
                jenkins_cli = GlueJenkins(
                    jenkins['url'], username=jenkins['user'], password=jenkins['password'])
                self.set_credit(
                    jenkins_cli,
                    jenkins['gitlab_credit'],
                    user='oauth2' if request.data['config']['token'] else request.data['config']['user'],
                    password=request.data['config']['token'] or request.data['config']['password'],
                    comment='GitLab'
                )

            except BaseException as e:
                print('err: ', e)

        if request.data['type'] == 'cicd-harbor':
            jenkins = get_redis_data('cicd-jenkins')
            harbor_config = json.loads(instance.config)
            harbor_credit = harbor_config.get('harbor_credit', None)
            try:
                comment = f'Harbor {request.data["name"]} at {datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")} by {request.user}'
                jenkins_cli = GlueJenkins(
                    jenkins['url'], username=jenkins['user'], password=jenkins['password'])
                self.set_credit
                self.set_credit(jenkins_cli, harbor_credit, self.request.data['config']['user'],
                                self.request.data['config']['password'], comment=comment)
                self.request.data['config']['harbor_credit'] = harbor_credit
            except BaseException as e:
                print('err: ', e)

        if request.data['type'] == 'cicd-jenkins':
            jenkins = get_redis_data('cicd-jenkins')
            jenkins_cli = GlueJenkins(request.data['config']['url'], username=request.data['config']['user'],
                                      password=request.data['config']['password'])
            secret = get_redis_data(
                request.data['config']['platform_secret'])['token']
            self.set_credit(
                jenkins_cli, jenkins['platform_credit'], secret=secret, comment='Platform')
            gitlab = get_redis_data('cicd-gitlab')
            self.set_credit(jenkins_cli, name=jenkins['gitlab_credit'],
                            user='oauth2' if gitlab['token'] else gitlab['user'],
                            password=gitlab['token'] or gitlab['password'], comment='GitLab')
        serializer = self.get_serializer(
            instance, data=request.data, partial=partial)
        if not serializer.is_valid():
            return Response({'code': 40000, 'status': 'failed', 'message': serializer.errors})
        try:
            self.perform_update(serializer)
        except BaseException as e:
            return Response({'code': 50000, 'status': 'failed', 'message': str(e)})

        if getattr(instance, '_prefetched_objects_cache', None):
            # If 'prefetch_related' has been applied to a queryset, we need to
            # forcibly invalidate the prefetch cache on the instance.
            instance._prefetched_objects_cache = {}

        log_audit(request, self.serializer_class.Meta.model.__name__, '更新', content=f"更新对象：{instance}",
                  data=serializer.data, old_data=self.serializer_class(instance).data)

        data = {'data': serializer.data, 'status': 'success', 'code': 20000}
        return Response(data)

    def perform_create(self, serializer):
        serializer.save()
        set_redis_data(serializer.data['name'], serializer.data['config'])

    def perform_update(self, serializer):
        serializer.save()
        set_redis_data(serializer.data['name'], serializer.data['config'])

    @action(methods=['POST'], url_path='test', detail=False)
    def test_conn(self, request):
        test_type = request.data['type']
        data = ''
        status = ''
        if test_type == 'robot':
            name = request.data['name']
            webhook = request.data['webhook']
            robot_type = request.data.get('robot_type', 'dingtalk')
            notify_key = request.data.get('key', None)
            taskid = async_task(test_notify, request.user.mobile, notify_type='robot', robot_name=name, robot_webhook=webhook,
                                robot_key=notify_key, robot_type=robot_type)
            ret = result(taskid)
            ret.get(3)
            data = ret.result['msg']
            data = ret.get('msg', '检测异常.')
            if ret.get('status', 1) != 0:
                status = 'failed'
            else:
                status = 'success'
        return Response({'code': 20000, 'status': status, 'data': data})
