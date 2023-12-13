#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
@Author : Charles Lai
@Contact : qqing_lai@hotmail.com
@Time : 2020/11/24 下午4:34
@FileName: filters.py
@Blog ：https://imaojia.com
"""

from __future__ import unicode_literals

import operator
from copy import deepcopy

from functools import reduce

from django.forms import JSONField
from django_filters.constants import EMPTY_VALUES
from django_filters.rest_framework.backends import DjangoFilterBackend
from django_filters import utils

from rest_framework.filters import OrderingFilter, SearchFilter
from django_filters import Filter, FilterSet, CharFilter, NumberFilter
from rest_framework.compat import distinct

from django.db import models
from elasticsearch_dsl import Q as EQ

from dbapp.models import AppInfo, MicroApp, BuildJob, AuditLog
from django_filters import filterset

import logging

logger = logging.getLogger('drf')


class JSONFilter(Filter):
    field_class = JSONField

    def filter(self, qs, value):
        if value in EMPTY_VALUES:
            return qs
        if self.distinct:
            qs = qs.distinct()
        lookup = '%s__%s' % (self.field_name, self.lookup_expr)
        if self.lookup_expr == 'contains':
            if not isinstance(value, list):
                value = str(value).split(',')
        qs = self.get_method(qs)(**{lookup: value})
        return qs


class CustomFilterSet(FilterSet):
    FILTER_DEFAULTS = deepcopy(filterset.FILTER_FOR_DBFIELD_DEFAULTS)
    FILTER_DEFAULTS.update({
        models.JSONField: {
            'filter_class': JSONFilter,
        },
    })


class CustomFilter(DjangoFilterBackend):
    # 自定义过滤
    default_filter_set = CustomFilterSet

    def get_filterset_class(self, view, queryset=None):
        """
        Return the `FilterSet` class used to filter the queryset.
        """
        filterset_class = getattr(view, 'filterset_class', None)
        filterset_fields = getattr(view, 'filterset_fields', None)

        if hasattr(view, 'get_filter_fields'):
            filterset_fields = getattr(view, 'get_filter_fields')()

        # TODO: remove assertion in 2.1
        if filterset_class is None and hasattr(view, 'filter_class'):
            utils.deprecate(
                "`%s.filter_class` attribute should be renamed `filterset_class`."
                % view.__class__.__name__)
            filterset_class = getattr(view, 'filter_class', None)

        # TODO: remove assertion in 2.1
        if filterset_fields is None and hasattr(view, 'filter_fields'):
            utils.deprecate(
                "`%s.filter_fields` attribute should be renamed `filterset_fields`."
                % view.__class__.__name__)
            filterset_fields = getattr(view, 'filter_fields', None)

        if filterset_class:
            filterset_model = filterset_class._meta.model

            # FilterSets do not need to specify a Meta class
            if filterset_model and queryset is not None:
                assert issubclass(queryset.model, filterset_model), \
                    'FilterSet model %s does not match queryset model %s' % \
                    (filterset_model, queryset.model)

            return filterset_class

        logger.debug(f'filterset_fields ====== {filterset_fields}')
        logger.debug(f'filterset_class ====== {filterset_class}')

        if filterset_fields and queryset is not None:
            MetaBase = getattr(self.filterset_base, 'Meta', object)
            logger.debug(
                f'filterset_base MetaBase======{self.filterset_base} {MetaBase}')

            class AutoFilterSet(self.filterset_base):
                class Meta(MetaBase):
                    model = queryset.model
                    fields = filterset_fields

            return AutoFilterSet

        return None


class CustomSearchFilter(SearchFilter):

    def get_search_fields(self, view, request):
        """
        Search fields are obtained from the view, but the request is always
        passed to this method. Sub-classes can override this method to
        dynamically change the search fields based on request content.
        """
        if hasattr(view, 'get_search_fields'):
            return view.get_search_fields()
        return getattr(view, 'search_fields', None)

    def get_search_terms(self, request):
        """
        Search terms are set by a ?search=... query parameter,
        and may be comma and/or whitespace delimited.
        """
        params = request.query_params.get(self.search_param, '')
        params = params.replace('\x00', '')  # strip null characters
        values = params.strip('+').split('+')
        if len(values) > 1:
            return values, 1
        params = params.replace(',', ' ')
        params = params.replace('|', ' ')
        return params.split(), 0

    def filter_queryset(self, request, queryset, view):
        search_fields = self.get_search_fields(view, request)
        search_param = self.get_search_terms(request)
        search_terms = search_param[0]
        search_condition = search_param[1]
        if not search_fields or not search_terms:
            return queryset

        orm_lookups = [
            self.construct_search(str(search_field))
            for search_field in search_fields
        ]

        base = queryset
        conditions = []
        for search_term in search_terms:
            queries = [
                models.Q(**{orm_lookup: search_term.strip()})
                for orm_lookup in orm_lookups
            ]
            conditions.append(reduce(operator.or_, queries))
        if search_condition == 1:
            queryset = queryset.filter(reduce(operator.and_, conditions))
        else:
            queryset = queryset.filter(reduce(operator.or_, conditions))

        if self.must_call_distinct(queryset, search_fields):
            # Filtering against a many-to-many field requires us to
            # call queryset.distinct() in order to avoid duplicate items
            # in the resulting queryset.
            # We try to avoid this if possible, for performance reasons.
            queryset = distinct(queryset, base)
        return queryset


class ExcludeFilter(Filter):

    def filter(self, qs, value):
        if not value:
            return qs
        value = value.strip(',').split(',')
        lookup = '%s__%s' % (self.field_name, self.lookup_expr)
        qs = self.get_method(qs)(**{lookup: value})
        return qs.distinct()


class ExcludeFilterEmptyValue(Filter):

    def filter(self, qs, value):
        if not value:
            return qs.none()
        value = value.strip(',').split(',')
        lookup = '%s__%s' % (self.field_name, self.lookup_expr)
        qs = self.get_method(qs)(**{lookup: value})
        return qs.distinct()


class M2MFilter(Filter):

    def filter(self, qs, value):
        if not value:
            return qs
        values = value.strip('+').split('+')
        if len(values) > 1:
            for v in values:
                qs = qs.filter(**{self.field_name: v})
            return qs.distinct()
        values = value.strip(',').split(',')
        if len(values) > 1:
            q = models.Q()
            q.connector = 'OR'
            for v in values:
                q.children.append((self.field_name, v))
            qs = qs.filter(q)
            return qs.distinct()
        lookup = '%s__%s' % (self.field_name, self.lookup_expr)
        qs = self.get_method(qs)(**{lookup: value})
        return qs.distinct()


class AppAssetFilter(FilterSet):
    tags__name = M2MFilter(distinct=True)

    class Meta:
        models = MicroApp
        fields = ['tags__name', 'platform']


class AppInfoFilter(FilterSet):
    tags__name = M2MFilter(distinct=True)
    hosts = M2MFilter(distinct=True)

    class Meta:
        models = AppInfo
        fields = ['tags__name', 'hosts']


class AuditLogFilter(FilterSet):
    exclude = ExcludeFilter(field_name='type', lookup_expr='in', exclude=True)
    type = CharFilter(field_name='type')

    class Meta:
        models = AuditLog
        fields = ['type', 'exclude']


class BuildJobFilter(FilterSet):
    app_include = ExcludeFilterEmptyValue(
        field_name='appinfo_id', lookup_expr='in')

    class Meta:
        models = BuildJob
        fields = ('app_include',)
