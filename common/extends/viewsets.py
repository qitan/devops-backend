#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
@Author  : Charles Lai
@Contact : qqing_lai@hotmail.com
@Time    : 19-11-11 下午3:33
@FileName: viewsets.py
@Blog    ：https://imaojia.com
"""

from __future__ import unicode_literals

import inspect

import django_filters
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.decorators import action
from rest_framework import viewsets
from rest_framework import pagination
from rest_framework.filters import OrderingFilter
from django.db import transaction
from django.shortcuts import get_object_or_404
from rest_framework_condition import last_modified
from django.db.models.query import QuerySet
from django.db.models import ProtectedError
from django.core.cache import cache

from common.utils.ElasticSearchAPI import Index
from common.extends.filters import CustomSearchFilter, CustomFilter
from common.extends.handler import log_audit
from common.extends.permissions import RbacPermission
import pytz
import logging

logger = logging.getLogger('api')


class CustomModelViewSet(viewsets.ModelViewSet):
    """
    A viewset that provides default `create()`, `retrieve()`, `update()`,
    `partial_update()`, `destroy()` and `list()` actions.
    """

    def get_permission_from_role(self, request):
        try:
            perms = request.user.roles.values(
                'permissions__method',
            ).distinct()
            return [p['permissions__method'] for p in perms]
        except AttributeError:
            return []

    def extend_filter(self, queryset):
        return queryset

    def get_queryset(self):
        """
        Get the list of items for this view.
        This must be an iterable, and may be a queryset.
        Defaults to using `self.queryset`.

        This method should always be used rather than accessing `self.queryset`
        directly, as `self.queryset` gets evaluated only once, and those results
        are cached for all subsequent requests.

        You may want to override this if you need to provide different
        querysets depending on the incoming request.

        (Eg. return a list of items that is specific to the user)
        """
        assert self.queryset is not None, (
            "'%s' should either include a `queryset` attribute, "
            "or override the `get_queryset()` method."
            % self.__class__.__name__
        )
        queryset = self.extend_filter(self.queryset)
        if isinstance(queryset, QuerySet):
            # Ensure queryset is re-evaluated on each request.
            queryset = queryset.all()
        return queryset.distinct()

    @action(methods=['GET'], url_path='count', detail=False)
    def count(self, request, *args, **kwargs):
        queryset = self.get_queryset()
        return Response({'code': 20000, 'data': queryset.count()})

    def create(self, request, *args, **kwargs):
        try:
            request.data['name'] = request.data['name'].strip(
                ' ').replace(' ', '-')
        except BaseException as e:
            print('exception ', str(e))
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

    def list(self, request, pk=None, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        page_size = request.query_params.get('page_size')
        pagination.PageNumberPagination.page_size = page_size
        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)
        serializer = self.get_serializer(queryset, many=True)
        data = {'data': {'total': queryset.count(), 'items': serializer.data},
                'code': 20000, 'status': 'success'}
        return Response(data)

    def update(self, request, *args, **kwargs):
        instance = self.get_object()
        partial = kwargs.pop('partial', False)
        try:
            request.data['name'] = request.data['name'].strip(
                ' ').replace(' ', '-')
        except BaseException as e:
            logger.warning(f'不包含name字段: {str(e)}')
        serializer = self.get_serializer(
            instance, data=request.data, partial=partial)
        if not serializer.is_valid():
            return Response({'code': 40000, 'status': 'failed', 'message': str(serializer.errors)})
        try:
            self.perform_update(serializer)
        except BaseException as e:
            logger.exception(f'更新失败，原因：{e}')
            return Response({'code': 50000, 'status': 'failed', 'message': str(e)})

        if getattr(instance, '_prefetched_objects_cache', None):
            # If 'prefetch_related' has been applied to a queryset, we need to
            # forcibly invalidate the prefetch cache on the instance.
            instance._prefetched_objects_cache = {}

        log_audit(request, self.serializer_class.Meta.model.__name__, '更新', content=f"更新对象：{instance}",
                  data=serializer.data, old_data=self.serializer_class(instance).data)

        data = {'data': serializer.data, 'status': 'success', 'code': 20000}
        return Response(data)

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance)
        data = {'data': serializer.data, 'code': 20000, 'status': 'success'}
        return Response(data)

    def destroy(self, request, *args, **kwargs):
        """
        TODO: 删除操作物理删除 or 逻辑删除(增加删除标记字段)
        """
        instance = self.get_object()
        try:
            self.perform_destroy(instance)
        except ProtectedError:
            # 存在关联数据，不可删除
            return Response({'code': 50000, 'status': 'failed', 'message': '存在关联数据，禁止删除！'})
        except BaseException as e:
            logger.exception(f'删除数据发生错误 {e}, {e.__class__}')
            return Response({'code': 50000, 'status': 'failed', 'message': f'删除异常： {str(e)}'})
        log_audit(request, self.serializer_class.Meta.model.__name__,
                  '删除', content=f"删除对象：{instance}")

        return Response({'code': 20000, 'status': 'success', 'msg': ''})


class CustomModelParentViewSet(CustomModelViewSet):

    def get_queryset(self):
        assert self.queryset is not None, (
            "'%s' should either include a `queryset` attribute, "
            "or override the `get_queryset()` method."
            % self.__class__.__name__
        )
        queryset = self.extend_filter(self.queryset)
        if self.action == 'list':
            if not self.request.query_params.get('search'):
                queryset = queryset.filter(parent__isnull=True)
        if isinstance(queryset, QuerySet):
            queryset = queryset.all()
        return queryset.distinct()
