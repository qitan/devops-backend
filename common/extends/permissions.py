#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
@Author : Charles Lai
@Contact : qqing_lai@hotmail.com
@Time : 2020/9/15 下午5:01
@FileName: permissions.py
@Blog ：https://imaojia.com
"""

from rest_framework.permissions import BasePermission
from dbapp.models import AuditLog

from common.get_ip import user_ip
from common.ext_fun import get_redis_data, get_members
import logging

logger = logging.getLogger('api')


class RbacPermission(BasePermission):
    """
    自定义权限
    """

    @classmethod
    def check_is_admin(cls, request):
        return request.user.is_authenticated and request.user.roles.filter(name='管理员').count() > 0

    @classmethod
    def get_permission_from_role(cls, request):
        try:
            perms = request.user.roles.values(
                'permissions__method',
            ).distinct()
            return [p['permissions__method'] for p in perms]
        except AttributeError:
            return []

    def _has_permission(self, request, view):
        """
        :return:
        """
        _method = request._request.method.lower()
        platform = get_redis_data('platform')
        url_whitelist = platform['whitelist'] if platform else []
        url_whitelist.extend(
            [{'url': '/api/login/feishu/'}, {'url': '/api/login/gitlab/'}])
        path_info = request.path_info
        for item in url_whitelist:
            url = item['url']
            if url in path_info:
                logger.debug(f'请求地址 {path_info} 命中白名单 {url}， 放行')
                return True

        from_workflow = 'from_workflow' in request.GET
        if _method == 'get' and from_workflow:
            return True

        is_superuser = request.user.is_superuser
        if is_superuser:
            return True

        is_admin = RbacPermission.check_is_admin(request)
        perms = self.get_permission_from_role(request)
        if not is_admin and not perms:
            logger.debug(f'用户 {request.user} 不是管理员 且 权限列表为空， 直接拒绝')
            return False

        perms_map = view.perms_map

        action = view.action
        _custom_method = f'{_method}_{action}'
        for i in perms_map:
            for method, alias in i.items():
                if is_admin and (method == '*' and alias[0] == 'admin'):
                    return True
                if method == '*' and alias[0] in perms:
                    return True
                if _custom_method and alias[0] in perms and (_custom_method == method or method == f'*_{action}'):
                    return True
                if _method == method and alias[0] in perms:
                    return True
        return False

    def has_permission(self, request, view):
        res = self._has_permission(request, view)
        # 记录权限异常的操作
        if not res:
            AuditLog.objects.create(
                user=request.user, type='', action='拒绝操作',
                action_ip=user_ip(request),
                content=f"请求方法：{request.method}，请求路径：{request.path}，UserAgent：{request.META['HTTP_USER_AGENT']}",
                data='',
                old_data=''
            )
        return res


class AdminPermission(BasePermission):

    def has_permission(self, request, view):
        if RbacPermission.check_is_admin(request):
            return True
        return False


class ObjPermission(BasePermission):
    """
    密码管理对象级权限控制
    """

    def has_object_permission(self, request, view, obj):
        perms = RbacPermission.get_permission_from_role(request)
        if 'admin' in perms:
            return True
        elif request.user.id == obj.uid_id:
            return True


class AppPermission(BasePermission):
    def has_object_permission(self, request, view, obj):
        return True


class AppInfoPermission(BasePermission):
    def has_object_permission(self, request, view, obj):
        return True


class AppDeployPermission(BasePermission):
    def has_object_permission(self, request, view, obj):
        return True
