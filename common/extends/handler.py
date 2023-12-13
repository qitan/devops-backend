#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
@Author : Charles Lai
@Contact : qqing_lai@hotmail.com
@Time : 2021/1/7 上午11:09
@FileName: handler.py
@Blog ：https://imaojia.com
"""

from dbapp.models import AuditLog

from common.get_ip import user_ip
from common.ext_fun import mask_sensitive_data


def log_audit(request, action_type, action, content=None, data=None, old_data=None, user=None):
    if user is None:
        user = request.user.first_name or request.user.username

    AuditLog.objects.create(user=user, type=action_type, action=action,
                            action_ip=user_ip(request),
                            content=f"{mask_sensitive_data(content)}\n请求方法：{request.method}，请求路径：{request.path}，UserAgent：{request.META['HTTP_USER_AGENT']}",
                            data=mask_sensitive_data(data),
                            old_data=mask_sensitive_data(old_data))
