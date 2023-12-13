#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
@Author : Charles Lai
@Contact : qqing_lai@hotmail.com
@Time : 2020/9/15 下午4:57
@FileName: renderers.py
@Blog ：https://imaojia.com
@Desc: from https://stackoverflow.com/questions/53910545/how-overwrite-response-class-in-django-rest-framework-drf
"""

from rest_framework.renderers import BaseRenderer
from rest_framework.utils import json


class ApiRenderer(BaseRenderer):

    def render(self, data, accepted_media_type=None, renderer_context=None):
        response_dict = {
            'status': 'failure',
            'data': {},
            'message': '',
        }
        if data.get('data'):
            response_dict['data'] = data.get('data')
        if data.get('status'):
            response_dict['status'] = data.get('status')
        if data.get('message'):
            response_dict['message'] = data.get('message')
        data = response_dict
        return json.dumps(data)
