#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
@Author : Charles Lai
@Contact : qqing_lai@hotmail.com
@Time : 2020/12/31 下午3:38
@FileName: get_ip.py
@Blog ：https://imaojia.com
"""


def user_ip(request):
    """
    获取用户真实IP
    :param request:
    :return:
    """
    if 'X-Real-IP' in request.META:
        return request.META['X-Real-IP']
    if 'HTTP_X_FORWARDED_FOR' in request.META:
        return request.META['HTTP_X_FORWARDED_FOR'].split(',')[0]
    if 'REMOTE_ADDR' in request.META:
        return request.META['REMOTE_ADDR'].split(',')[0]
