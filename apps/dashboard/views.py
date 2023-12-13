#!/usr/bin/env python
# -*- encoding: utf-8 -*-
'''
@Author  :    Charles Lai
@Contact :    qqing_lai@hotmail.com
@Time    :    2021/12/27 17:47
@FileName:    views.py
@Blog    :    https://imaojia.com
'''

import random
from functools import reduce
import operator
from jira import Project
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.decorators import action
from django.db.models import Q, Count, Sum, Avg
from django.db.models.query import QuerySet
from django.apps import apps
from django.db.models.functions import ExtractWeek, ExtractYear, ExtractDay, ExtractMonth

from elasticsearch_dsl import Q as EQ
from common.utils.ElasticSearchAPI import Search

from dbapp.model.model_cmdb import Product, MicroApp
from common.ext_fun import get_datadict, get_time_range

from common.extends.viewsets import CustomModelViewSet

import logging
from common.variables import CMDB_RELATED_TYPE, DASHBOARD_CONFIG, DASHBOARD_TIME_FORMAT_T, DASHBOARD_TIME_FORMAT_T_ES

from dbapp.model.model_dashboard import DashBoard
from dashboard.serializers import DashBoardSerializers
from dbapp.model.model_deploy import BuildJob

logger = logging.getLogger(__name__)


class LiveCheck(APIView):
    """
    探针检测
    """
    permission_classes = []

    def get(self, request, format=None):
        return Response('PONG')


class DashBoardViewSet(CustomModelViewSet):
    """
    仪表盘视图

    ### 仪表盘权限
        {'*': ('dashboard_all', '仪表盘管理')},
        {'get': ('dashboard_list', '查看仪表盘')},
        {'post': ('dashboard_create', '创建仪表盘')},
        {'put': ('dashboard_edit', '编辑仪表盘')},
        {'patch': ('dashboard_edit', '编辑仪表盘')},
        {'delete': ('dashboard_delete', '删除仪表盘')}
    """
    perms_map = (
        {'*': ('admin', '管理员')},
        {'*': ('dashboard_all', '仪表盘管理')},
        {'get': ('dashboard_list', '查看仪表盘')},
        {'post': ('dashboard_create', '创建仪表盘')},
        {'put': ('dashboard_edit', '编辑仪表盘')},
        {'patch': ('dashboard_edit', '编辑仪表盘')},
        {'delete': ('dashboard_delete', '删除仪表盘')}
    )
    queryset = DashBoard.objects.all()
    serializer_class = DashBoardSerializers
    filter_fields = ('name', 'type', )
    search_fields = ('name', 'type', )
    model_product = Product
    model_project = Project
    model_microapp = MicroApp
    model_deploy = BuildJob
    # 图表颜色
    success_color = ['#91cc75', '#759aa0', '#8dc1a9', '#73a373', '#7289ab', '#37A2DA', '#32C5E9', '#67E0E3', '#9FE6B8',
                     '#9d96f5', '#8378EA', '#96BFFF']
    failed_color = ['#ee6666', '#dd6b66', '#e69d87', '#ea7e53', '#ff9f7f', '#fb7293', '#E062AE', '#E690D1', '#e7bcf3',
                    '#f49f42', '#FFDB5C', '#eedd78']

    def get_es_queryset(self, model, period, time_field=None, filter_field=None, conditions=None, filter_conditions=None, count_only=False,
                        group_by=False, size=None, metric=False, disable_region=False, disable_env=False, disable_product=False, *args, **kwargs):
        """
        :param model: ES Search实例
        :param period: 时间区间
        :param time_field: 过滤的时间字段
        :param filter_field: 过滤的字段
        :param conditions: OR条件
        :param filter_conditions: AND条件
        :param count_only: 只统计数量
        :param group_by: 分组统计
        :param metric: 分组统计并汇集数据
        :param disable_region: 不区分地区
        :param disable_env: 不区分环境
        :param disable_product: 不区分产品
        :param size:
        """
        if not size:
            size = self.config_check([])[1]
        if not time_field:
            time_field = 'S-creation-time'
        end_time = period['end_time'].strftime(
            DASHBOARD_TIME_FORMAT_T[period['name']])
        start_time = period['start_time'].strftime(
            DASHBOARD_TIME_FORMAT_T[period['name']])
        date_format = DASHBOARD_TIME_FORMAT_T_ES[period['name']]
        es_filter = []
        if disable_region is False:
            region = self.request.query_params.get('region', None)
            if region:
                es_filter = [EQ('match', region_info__name=region)]
        if disable_env is False:
            environment = self.request.query_params.get('environment', None)
            if environment:
                es_filter.append(EQ('match', environment=environment))
        if disable_product is False:
            product = self.request.query_params.get('product', None)
            if product:
                es_filter.append(EQ('match', product_info__id=product))
        if kwargs:
            es_filter.append(EQ('match', **kwargs))
        if es_filter:
            model = model.filter(reduce(operator.and_, es_filter))
        if filter_conditions:
            model = model.filter(filter_conditions)
        if period and time_field:
            model = model.filter(
                'range', **{time_field: {'gt': period['start_time'], 'lt': period['end_time']}})
        if conditions:
            model = model.query(conditions)
        if count_only:
            return model.count()
        if group_by or metric:
            if metric:
                model.aggs.bucket('app', 'terms', field=filter_field, min_doc_count=1, size=size).metric('top_n_hits',
                                                                                                         'top_hits',
                                                                                                         size=1)
            else:
                model.aggs.bucket(
                    'app', 'terms', field=filter_field, min_doc_count=0, size=size)
            try:
                return model.execute().aggregations.app.buckets
            except BaseException as e:
                logger.exception(f'获取app bucket异常，{e}')
        model.aggs.bucket('count', 'date_histogram', field=time_field, min_doc_count=0,
                          extended_bounds={'min': start_time, 'max': end_time}, format=date_format,
                          time_zone='Asia/Shanghai', interval=period['name'].rstrip('s'))
        try:
            return model.execute().aggregations.count.buckets
        except BaseException as e:
            logger.exception(f'获取count bucket异常，{e}')
            return []

    @staticmethod
    def get_model_queryset(model, period, **kwargs):
        end_time = period['end_time']
        start_time = period['start_time']
        queryset = model.filter(
            created_time__gt=start_time, created_time__lt=end_time, **kwargs)
        # 按天统计
        date_format = DASHBOARD_TIME_FORMAT_T[period['name']].replace(
            '%', '%%')
        queryset = queryset.extra(
            select={
                "created_time": f"DATE_FORMAT(CONVERT_TZ({model.model._meta.db_table}.created_time, 'GMT', 'Asia/Shanghai'), '{date_format}')"}
        ).values('created_time').annotate(count=Count('created_time')).values('created_time', 'count').order_by(
            'created_time')
        return {i['created_time']: i['count'] for i in queryset}

    @staticmethod
    def get_model(module, model):
        # 数据模型统一管理
        module = 'dbapp'
        return apps.all_models[module][model]

    def get_object(self):
        if self.action == 'retrieve':
            _key = 'name'
            self.kwargs[
                _key] = f"dashboard.{self.kwargs[self.lookup_url_kwarg or self.lookup_field]}.{self.request.user.username}"
            self.lookup_field = _key
        try:
            return super().get_object()
        except BaseException as e:
            return None

    def model_filter(self, region):
        return {'appinfo': {'app__project__product__region__name': region},
                'microapp': {'project__product__region__name': region}, 'product': {'region__name': region},
                'project': {'product__region__name': region}, 'kubernetescluster': {'idc__region__name': region},
                'publishorder': {'region': region}}

    def get_model_ext(self, module, model):
        queryset = self.get_model(module, model).objects.all()
        region = self.request.query_params.get('region', None)
        if region:
            try:
                model_filter = self.model_filter(region)
                queryset = queryset.filter(**model_filter[model])
            except BaseException as e:
                pass
        return queryset.distinct()

    def get_es_ext(self, model, time_field='-created_time'):
        s = Search(prefix=True, index=f"{model}").source(**{'excludes': ['result', 'console_output']}).sort(
            time_field)
        return s

    def get_dashboard_config(self, chart_type):
        try:
            queryset = self.queryset.get(
                name=f'dashboard.{chart_type}.{self.request.user.username}')
            config = queryset.config
        except BaseException as e:
            config = get_datadict(f'dashboard.{chart_type}', config=1)
        if config is None:
            try:
                config = DASHBOARD_CONFIG[chart_type]
            except BaseException as e:
                logger.warning('未找到报表配置')
                config = []
        return config

    @staticmethod
    def get_random_app(region=None):
        if region:
            apps = MicroApp.objects.filter(
                project__product__region__name=region).order_by('?')[:12]
        else:
            apps = MicroApp.objects.order_by('?')[:12]
        return apps

    @staticmethod
    def config_check(config):
        try:
            config_limit = int(get_datadict('dashboard.limit')['value'])
        except BaseException as e:
            config_limit = 12
        if (len(config)) > config_limit:
            return False, config_limit
        return True, config_limit

    def create(self, request, *args, **kwargs):
        chart_type = request.data.get('type', 'index')
        if request.data.get('config', None) is None:
            request.data['config'] = get_datadict(
                f'dashboard.{chart_type}', config=1)
        _check = self.config_check(request.data['config'])
        if _check[0] is False:
            return Response({'code': 40000, 'message': f'展示模型最多可配置{_check[1]}个!'})
        request.data['name'] = f"dashboard.{chart_type}.{request.user.username}"
        return super().create(request, *args, **kwargs)

    def perform_create(self, serializer):
        serializer.save(creator=self.request.user)

    def update(self, request, *args, **kwargs):
        _check = self.config_check(request.data['config'])
        if _check[0] is False:
            return Response({'code': 40000, 'message': f'展示模型最多可配置{_check[1]}个!'})
        return super().update(request, *args, **kwargs)

    def perform_destroy(self, instance):
        try:
            return super().perform_destroy(instance)
        except BaseException as e:
            return None

    @action(methods=['GET'], detail=False, url_path='model')
    def dashboard_config_model(self, request):
        """
        获取可用于报表的模型
        """
        # 关系型数据库表关联
        data = []
        d_models = apps.all_models
        rds = [{'type': 'rds', 'key': v._meta.verbose_name, 'value': f"{i}.{k}",
                'icon': getattr(v.ExtMeta, 'icon', 'nested')} for i, _models in d_models.items() for
               k, v in _models.items() if getattr(v, 'ExtMeta', None) and v.ExtMeta.dashboard]
        data.append({'label': dict(CMDB_RELATED_TYPE)[1], 'options': rds})
        return Response({'code': 20000, 'data': data})

    @action(methods=['GET'], detail=False, url_path='panel')
    def dashboard_panel_count(self, request):
        """
        Dashboard报表

        数量统计
        """
        panels = [
            {'key': '产品', 'icon': 'asset4', 'type': 'rds', 'value': 'cmdb.product'},
            {'key': '项目', 'icon': 'tree-table',
             'type': 'rds', 'value': 'cmdb.project'},
            {'key': '应用', 'icon': 'component',
             'type': 'rds', 'value': 'cmdb.microapp'},
            {'key': '应用模块', 'icon': 'nested', 'type': 'rds', 'value': 'cmdb.appinfo'}, ]
        data = []
        for model in panels:
            count = 0
            if model['type'] == 'rds':
                # 关系型数据库表
                count = self.get_model_ext(model['value'].split(
                    '.')[0], model['value'].split('.')[1]).count()
            data.append(
                {'name': model['value'], 'alias': model['key'], 'count': count, 'icon': model.get('icon', 'nested')})
        return Response({'code': 20000, 'data': data})

    @action(methods=['GET'], detail=False, url_path='cmdb/panel')
    def cmdb_panel_count(self, request):
        """
        资产概览 - count

        数量统计
        """
        panels = self.get_dashboard_config('cmdb')
        data = []
        for model in panels:
            count = 0
            if model['type'] == 'rds':
                # 关系型数据库表
                count = self.get_model_ext(model['value'].split(
                    '.')[0], model['value'].split('.')[1]).count()
            data.append(
                {'name': model['value'], 'alias': model['key'], 'count': count, 'icon': model.get('icon', 'nested')})
        return Response({'code': 20000, 'data': data})

    @action(methods=['GET'], detail=False, url_path='cmdb/line')
    def cmdb_line(self, request):
        """
        资产概览 - chart/line

        拆线图
        """
        period_time = get_time_range(request)
        period = period_time[0]
        time_line = period_time[1]
        panels = self.get_dashboard_config('cmdb')
        series = []
        for model in panels:
            data = []
            if model['type'] == 'rds':
                queryset = self.get_model_ext(model['value'].split('.')[
                                              0], model['value'].split('.')[1])
                qs = self.get_model_queryset(queryset, period)
                data = [qs.get(i, 0) for i in time_line]
            series.append(
                {'name': model['key'], 'type': 'line', 'smooth': True, 'data': data})
        data = {
            'title': {'text': '资产统计'},
            'tooltip': {'trigger': 'axis', 'transitionDuration': 0},
            'legend': {'data': [i['key'] for i in panels]},
            'grid': {
                'left': '20px',
                'right': '25px',
                'bottom': '5%',
                'containLabel': True
            },
            'toolbox': {'feature': {'saveAsImage': {}}, 'itemSize': '16', 'right': '8px'},
            'xAxis': {'type': 'category', 'boundaryGap': False, 'data': period_time[2]},
            'yAxis': {'type': 'value'},
            'series': series
        }
        return Response({'code': 20000, 'data': data})

    @action(methods=['GET'], detail=False, url_path='cicd/bar_pie/time')
    def cicd_bar_pie_time(self, request):
        """
        CICD报表 - chart/bar

        柱状图&饼图 构建发布/时间
        """
        app_ids = request.query_params.getlist('app_ids[]', [])
        if len(app_ids) == 0:
            app_ids = [i['id'] for i in self.get_dashboard_config('deploy')]
        apps = MicroApp.objects.filter(id__in=app_ids)
        conditions = [EQ('match_phrase', appid=j.appid) for j in apps]
        period_time = get_time_range(request)
        period = period_time[0]
        time_line = period_time[1]
        series = []
        panels = [{'key': '应用构建', 'value': 'buildjob-*', 'stack': 'BuildJob'},
                  {'key': '版本发布', 'value': 'deployjob-*', 'stack': 'DeployJob'}]
        status_map = [{'status': 1, 'label': '成功', 'color': self.success_color},  # ['#67c23a', '#7ddb4e']},
                      {'status': 2, 'label': '失败', 'color': self.failed_color}]  # ['#dd395f', '#f72c5b']}]
        filter_field = []
        for index, model in enumerate(panels):
            # 构建/发布统计
            queryset = self.get_es_ext(model['value'])
            for stat in status_map:
                stat_filter = [EQ('match', status=stat['status'])]
                if filter_field:
                    stat_filter.extend(filter_field)
                if apps:
                    qs = self.get_es_queryset(queryset, period, time_field='created_time',
                                              conditions=reduce(
                                                  operator.or_, conditions),
                                              filter_conditions=reduce(operator.and_, stat_filter))
                else:
                    qs = self.get_es_queryset(queryset, period, time_field='created_time',
                                              filter_conditions=reduce(operator.and_, stat_filter))
                data = [j.doc_count for j in qs if j.key_as_string in time_line]
                series.append(
                    {'name': f"{model['key'][2:]}{stat['label']}", 'type': 'bar', 'barMaxWidth': '60',
                     'label': {'show': True, 'color': '#606266'},
                     'itemStyle': {'opacity': '0.95',
                                   'color': stat['color'][random.randint(0, len(stat['color']) - 1)]},
                     'stack': model['stack'], 'data': data})
        pie_status_map = [{'deploy_type': 0, 'label': '应用发布', 'color': '#91cc75'},
                          {'deploy_type': 2, 'label': '应用回退', 'color': '#ee6666'}]
        queryset = self.get_es_ext('deployjob-*')
        pie_data = []
        try:
            for stat in pie_status_map:
                stat_filter = [EQ('match', deploy_type=stat['deploy_type'])]
                if filter_field:
                    stat_filter.extend(filter_field)
                if apps:
                    qs = self.get_es_queryset(queryset, period, time_field='created_time',
                                              conditions=reduce(operator.or_, conditions), count_only=True,
                                              filter_conditions=reduce(operator.and_, stat_filter))
                else:
                    qs = self.get_es_queryset(queryset, period, time_field='created_time', count_only=True,
                                              filter_conditions=reduce(operator.and_, stat_filter))
                pie_data.append(
                    {'name': stat['label'], 'value': qs, 'itemStyle': {'opacity': '0.95', 'color': stat['color']}})
            series.append(
                {'name': '应用发布', 'type': 'pie', 'radius': [0, '60%'], 'center': ['82%', '50%'],
                 'label': {'formatter': '{b}: {c} ({d}%)', 'show': True}, 'selectedMode': 'single',
                 'tooltip': {'trigger': 'item', 'formatter': '{b} : {c} ({d}%)'}, 'data': pie_data})
        except BaseException as e:
            logger.debug(f"饼图生成异常, 原因: {e}")
        data = {
            'title': [{'text': '构建发布/时间'}, {'left': '70%', 'text': '应用发布'}],
            'tooltip': {'trigger': 'axis'},
            'legend': {'data': [f"{i['key'][2:]}{j['label']}" for i in panels for j in status_map], 'left': '20%'},
            'grid': [
                {'width': '61%', 'left': '20px', 'right': '20px',
                    'bottom': '5%', 'containLabel': True},
                {'width': '37%', 'left': '20px', 'right': '25px',
                    'bottom': '5%', 'containLabel': True}
            ],
            'toolbox': {'feature': {'saveAsImage': {}}, 'itemSize': '16', 'right': '8px'},
            'xAxis': [{'type': 'category', 'boundaryGap': False, 'data': period_time[2], 'width': '62%'},
                      {'gridIndex': 1, 'type': 'category', 'boundaryGap': False, 'show': False}],
            'yAxis': [{'type': 'value'}, {'gridIndex': 1, 'type': 'value', 'show': False}],
            'series': series
        }
        return Response({'code': 20000, 'data': data})

    @action(methods=['GET'], detail=False, url_path='cicd/bar_pie/app')
    def cicd_bar_pie_app(self, request):
        """
        CICD报表 - chart/bar/app

        柱状图&饼图 构建发布/应用
        """
        app_ids = request.query_params.getlist('app_ids[]', [])
        period_time = get_time_range(request)
        period = period_time[0]
        if len(app_ids) == 0:
            app_ids = [i['id'] for i in self.get_dashboard_config('deploy')]
        # 从最近构建应用中获取
        queryset = self.get_es_ext('deployjob-*')
        try:
            app_ids = self.get_es_queryset(
                queryset, period, time_field='created_time', filter_field='appid', group_by=True)
        except BaseException as e:
            logger.debug(f"构建发布/应用统计异常, 原因: {e}")
            app_ids = self.get_es_queryset(queryset, period, time_field='created_time', filter_field='appid.keyword',
                                           group_by=True)
        series = []
        panels = [{'key': '应用构建', 'value': 'buildjob-*', 'stack': 'BuildJob'},
                  {'key': '版本发布', 'value': 'deployjob-*', 'stack': 'DeployJob'}]
        status_map = [{'status': 1, 'label': '成功', 'color': self.success_color},
                      {'status': 2, 'label': '失败', 'color': self.failed_color}]
        filter_field = []
        for index, model in enumerate(panels):
            # 构建/发布统计
            queryset = self.get_es_ext(model['value'])
            for stat in status_map:
                data = []
                for appid in app_ids:
                    if filter_field:
                        qs = self.get_es_queryset(queryset, period, time_field='created_time',
                                                  conditions=EQ('match_phrase', appid=appid['key']), count_only=True,
                                                  filter_conditions=reduce(
                                                      operator.and_, filter_field),
                                                  status=stat['status'])
                    else:
                        qs = self.get_es_queryset(queryset, period, time_field='created_time',
                                                  conditions=EQ('match_phrase', appid=appid['key']), count_only=True,
                                                  status=stat['status'])
                    data.append(qs)
                # 柱状图
                series.append(
                    {'name': f"{model['key'][2:]}{stat['label']}", 'type': 'bar', 'barMaxWidth': '60',
                     'itemStyle': {'opacity': '0.95'}, 'label': {'show': True, 'color': '#606266'},
                     'color': stat['color'][random.randint(0, len(stat['color']) - 1)], 'stack': model['stack'],
                     'data': data})
        # 饼图
        pie_names = [{'name': 'product', 'alias': '产品', 'radius': ['50%', '70%'], 'select_mode': 'single'},
                     {'name': 'project', 'alias': '项目', 'radius': [0, '40%'], 'select_mode': 'multiple'}]
        try:
            conditions = []
            for pie in pie_names:
                queryset = self.get_es_ext('deployjob-*')
                qs = self.get_es_queryset(queryset, period, time_field='created_time', filter_field=f"{pie['name']}_info.name.keyword",
                                          conditions=reduce(
                                              operator.or_, conditions) if conditions else [],
                                          group_by=True)
                conditions = [
                    EQ('match_phrase', **{'product_info.name': i['key']}) for i in qs]
                pie_data = [{'name': i['key'], 'value': i['doc_count'], 'itemStyle': {
                    'opacity': '0.95'}} for i in qs if i['doc_count']]
                series.append(
                    {'name': pie['alias'], 'type': 'pie', 'radius': pie['radius'], 'center': ['83%', '49%'],
                     'selectedMode': pie['select_mode'],
                     'label': {'formatter': '{b}: {d}%', 'show': True},
                     'tooltip': {'trigger': 'item', 'formatter': '{a} <br/>{b} : {c} ({d}%)'}, 'data': pie_data})
        except BaseException as e:
            logger.debug(f"饼图生成异常, 原因: {e}")
        data = {
            'title': [{'text': '构建发布/应用'}, {'left': '70%', 'text': '产品项目'}],
            'tooltip': {'trigger': 'axis'},
            'legend': {'data': [f"{i['key'][2:]}{j['label']}" for i in panels for j in status_map], 'left': '20%'},
            'grid': [
                {'width': '61%', 'left': '20px', 'right': '20px',
                    'bottom': '5%', 'containLabel': True},
                {'width': '37%', 'left': '20px', 'right': '25px',
                    'bottom': '5%', 'containLabel': True}
            ],
            'toolbox': {'feature': {'saveAsImage': {}}, 'itemSize': '16', 'right': '8px'},
            'xAxis': [
                {'type': 'category', 'boundaryGap': False, 'data': [i['key'] for i in app_ids],
                 'width': '62%'},
                {'gridIndex': 1, 'type': 'category', 'boundaryGap': False, 'show': False}],
            'yAxis': [{'type': 'value'}, {'gridIndex': 1, 'type': 'value', 'show': False}],
            'series': series
        }
        return Response({'code': 20000, 'data': data})
