#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
@Author : Charles Lai
@Contact : qqing_lai@hotmail.com
@Time : 2020/9/15 下午5:19
@FileName: pagination.py
@Blog ：https://imaojia.com
"""

from rest_framework.pagination import PageNumberPagination, LimitOffsetPagination
from rest_framework.response import Response


class CustomPagination(PageNumberPagination):
    def get_paginated_response(self, data):
        return Response({
            'data': {'items': data, 'total': self.page.paginator.count},
            'code': 20000,
            'next': self.get_next_link(),
            'previous': self.get_previous_link()
        })
