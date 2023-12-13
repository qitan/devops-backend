#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
@Author : Charles Lai
@Contact : qqing_lai@hotmail.com
@Time : 2021/05/13 下午4:15
@FileName: view_cmdb
@Blog : https://imaojia.com
"""
import time
import shortuuid

from django_q.tasks import async_task, schedule, result
from django_q.models import Schedule
from django.utils.decorators import method_decorator
from django.core.cache import caches
from qtasks.tasks_build import JenkinsBuild
from cmdb.serializer.serializer_cmdb import ProductWithProjectsSerializers, ProductSerializers, \
    ProjectConfigSerializers, ProjectEnvReleaseConfigSerializers

from common.extends.decorators import appinfo_order_check
from rest_framework.permissions import IsAuthenticated
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.filters import SearchFilter, OrderingFilter

from django.db import transaction
from django.core.cache import cache
from django.views.decorators.cache import cache_page

from elasticsearch_dsl import Q as EQ

import django_filters

from dbapp.models import *
from common.utils.AtlassianJiraAPI import JiraAPI
from dbapp.model.model_deploy import BuildJob, BuildJobResult, DeployJob
from dbapp.model.model_ucenter import Menu, DataDict
from cmdb.serializers import ProductSerializers, EnvironmentSerializers, \
    KubernetesClusterSerializers, KubernetesClusterListSerializers, ProjectListSerializers, ProjectSerializers, \
    MicroAppListSerializers, MicroAppSerializers, MicroAppListForPermApplySerializers, \
    AppInfoListSerializers, AppInfoListForCdSerializers, AppInfoListForCiSerializers, AppInfoListForDeploySerializers, \
    AppInfoListForOrderSerializers, AppInfoSerializers, \
    DevLanguageSerializers, RegionSerializers, RegionProductSerializers
from dbapp.model.model_ucenter import Menu, SystemConfig

from common.extends.viewsets import CustomModelViewSet, CustomModelParentViewSet
from common.extends.permissions import RbacPermission, AppPermission, AppInfoPermission
from common.extends.filters import CustomSearchFilter
from common.extends.handler import log_audit

from common.utils.ElasticSearchAPI import Search
from common.utils.JenkinsAPI import GlueJenkins
from common.utils.GitLabAPI import GitLabAPI
from common.utils.HarborAPI import HarborAPI
from common.custom_format import convert_xml_to_str_with_pipeline
from common.utils.RedisAPI import RedisManage
from common.ext_fun import get_datadict, get_permission_from_role, get_redis_data, gitlab_cli, k8s_cli, set_redis_data, \
    template_generate, devlanguage_template_manage, get_project_mergerequest

from config import CONFIG_CENTER_DEFAULT_USER, CONFIG_CENTER_DEFAULT_PASSWD, JIRA_CONFIG, SOCIAL_AUTH_GITLAB_API_URL, TB_CONFIG

from functools import reduce
from ruamel import yaml
from datetime import datetime, timedelta
import json
import os
import operator
import xlwt
import logging

logger = logging.getLogger('drf')


class DevLanguageViewSet(CustomModelViewSet):
    """
    开发语言视图

    ### 开发语言权限
        {'*': ('env_all', '区域环境管理')},
        {'get': ('env_list', '查看区域环境')},
        {'post': ('env_create', '创建区域环境')},
        {'put': ('env_edit', '编辑区域环境')},
        {'patch': ('env_edit', '编辑区域环境')},
        {'delete': ('env_delete', '删除区域环境')}
    """
    perms_map = (
        {'*': ('admin', '管理员')},
        {'*': ('env_all', '区域环境管理')},
        {'get': ('env_list', '查看区域环境')},
        {'post': ('env_create', '创建区域环境')},
        {'put': ('env_edit', '编辑区域环境')},
        {'patch': ('env_edit', '编辑区域环境')},
        {'delete': ('env_delete', '删除区域环境')}
    )
    queryset = DevLanguage.objects.all()
    serializer_class = DevLanguageSerializers

    @action(methods=['GET'], url_path='template', detail=True)
    def language_template(self, request, pk=None):
        """
        开发语言模板

        参数:
            template: 模板名称
        """
        instance = self.get_object()
        name = request.query_params.get('template', None)
        if name is None:
            return Response({'code': 50000, 'message': '模板不存在!'})
        ok, content = devlanguage_template_manage(
            instance, DEV_LANGUAGE_FILE_MAP[name])
        if not ok:
            return Response({'code': 50000, 'message': content})
        return Response({'code': 20000, 'data': content})

    def partial_update(self, request, *args, **kwargs):
        instance = self.get_object()
        kwargs['partial'] = True
        try:
            for i in request.data:
                if DEV_LANGUAGE_FILE_MAP.get(i, None):
                    devlanguage_template_manage(instance, DEV_LANGUAGE_FILE_MAP[i], self.request.user, request.data[i],
                                                'update')
        except BaseException as e:
            logger.exception(f"更新开发语言[{instance}]异常, 原因: {e}")
        return self.update(request, *args, **kwargs)


class RegionViewSet(CustomModelViewSet):
    """
    区域视图

    ### 区域权限
        {'*': ('env_all', '区域环境管理')},
        {'get': ('env_list', '查看区域环境')},
        {'post': ('env_create', '创建区域环境')},
        {'put': ('env_edit', '编辑区域环境')},
        {'patch': ('env_edit', '编辑区域环境')},
        {'delete': ('env_delete', '删除区域环境')}
    """
    perms_map = (
        {'*': ('admin', '管理员')},
        {'*': ('env_all', '区域环境管理')},
        {'get': ('env_list', '查看区域环境')},
        {'post': ('env_create', '创建区域环境')},
        {'put': ('env_edit', '编辑区域环境')},
        {'patch': ('env_edit', '编辑区域环境')},
        {'delete': ('env_delete', '删除区域环境')}
    )
    queryset = Region.objects.all()
    serializer_class = RegionSerializers
    filter_backends = (django_filters.rest_framework.DjangoFilterBackend,
                       CustomSearchFilter, OrderingFilter)
    filter_fields = ('name', 'alias', 'is_enable')
    search_fields = ('name', 'alias', 'desc')

    def get_serializer_class(self):
        if self.action == 'get_region_product':
            return RegionProductSerializers
        return RegionSerializers

    @action(methods=['GET'], url_path='product', detail=False)
    def get_region_product(self, request):
        # 获取区域产品
        return super().list(request)


class ProductViewSet(CustomModelParentViewSet):
    """
    项目产品视图

    ### 产品权限
        {'*': ('env_all', '产品环境管理')},
        {'get': ('env_list', '查看产品环境')},
        {'post': ('env_create', '创建产品环境')},
        {'put': ('env_edit', '编辑产品环境')},
        {'patch': ('env_edit', '编辑产品环境')},
        {'delete': ('env_delete', '删除产品环境')}
    """
    perms_map = (
        {'*': ('admin', '管理员')},
        {'*': ('env_all', '产品环境管理')},
        {'get': ('env_list', '查看产品环境')},
        {'post': ('env_create', '创建产品环境')},
        {'put': ('env_edit', '编辑产品环境')},
        {'patch': ('env_edit', '编辑产品环境')},
        {'delete': ('env_delete', '删除产品环境')}
    )
    queryset = Product.objects.all()
    serializer_class = ProductSerializers
    filter_backends = (django_filters.rest_framework.DjangoFilterBackend,
                       CustomSearchFilter, OrderingFilter)
    filter_fields = ('id', 'name', 'alias')
    search_fields = ('name', 'alias', 'desc')

    def get_serializer_class(self, *args, **kwargs):
        if self.action == 'product_projects':
            return ProductWithProjectsSerializers
        return super().get_serializer_class()

    @action(methods=['GET'], url_path='projects', detail=False)
    def product_projects(self, request, pk=None, *args, **kwargs):
        return super().list(request, pk, *args, **kwargs)


class EnvironmentViewSet(CustomModelViewSet):
    """
    项目环境视图

    ### 环境权限
        {'*': ('env_all', '区域环境管理')},
        {'get': ('env_list', '查看区域环境')},
        {'post': ('env_create', '创建区域环境')},
        {'put': ('env_edit', '编辑区域环境')},
        {'patch': ('env_edit', '编辑区域环境')},
        {'delete': ('env_delete', '删除区域环境')}
    """
    perms_map = (
        {'*': ('admin', '管理员')},
        {'*': ('env_all', '区域环境管理')},
        {'get': ('env_list', '查看区域环境')},
        {'post': ('env_create', '创建区域环境')},
        {'put': ('env_edit', '编辑区域环境')},
        {'patch': ('env_edit', '编辑区域环境')},
        {'delete': ('env_delete', '删除区域环境')}
    )
    queryset = Environment.objects.all()
    serializer_class = EnvironmentSerializers
    filter_backends = (django_filters.rest_framework.DjangoFilterBackend,
                       CustomSearchFilter, OrderingFilter)
    filter_fields = ('name', 'ticket_on')
    search_fields = ('desc',)

    @action(methods=['GET'], detail=False, url_path='cicd')
    def env_for_cicd(self, request):
        # 获取允许CICD的环境
        queryset = self.extend_filter(self.queryset)
        serializer = self.get_serializer(queryset, many=True)
        data = {'data': {'total': queryset.count(), 'items': serializer.data},
                'code': 20000, 'status': 'success'}
        return Response(data)

    @action(methods=['GET'], detail=False, url_path='ticket')
    def env_for_ticket(self, request):
        # 获取需要工单申请的环境
        return super().env_for_cicd(request)


class KubernetesClusterViewSet(CustomModelViewSet):
    """
    Kubernetes集群视图

    ### Kubernetes集群权限
        {'*': ('k8scluster_all', 'k8s集群管理')},
        {'get': ('k8scluster_list', '查看k8s集群')},
        {'post': ('k8scluster_create', '创建k8s集群')},
        {'put': ('k8scluster_edit', '编辑k8s集群')},
        {'patch': ('k8scluster_edit', '编辑k8s集群')},
        {'delete': ('k8scluster_delete', '删除k8s集群')}
    """
    perms_map = (
        {'*': ('admin', '管理员')},
        {'*': ('k8scluster_all', 'k8s集群管理')},
        {'get': ('k8scluster_list', '查看k8s集群')},
        {'post': ('k8scluster_create', '创建k8s集群')},
        {'put': ('k8scluster_edit', '编辑k8s集群')},
        {'patch': ('k8scluster_edit', '编辑k8s集群')},
        {'delete': ('k8scluster_delete', '删除k8s集群')}
    )
    queryset = KubernetesCluster.objects.all()
    serializer_class = KubernetesClusterSerializers
    filter_backends = (django_filters.rest_framework.DjangoFilterBackend,
                       CustomSearchFilter, OrderingFilter)
    filter_fields = ('name', 'environment', 'environment__name')
    search_fields = ('name', 'environment', 'environment__name')

    def get_serializer_class(self):
        if self.action in ['list', 'retrieve']:
            return KubernetesClusterListSerializers
        return KubernetesClusterSerializers

    @action(methods=['GET'], url_path='config', detail=True)
    def kubernetes_config(self, request, pk=None):
        """
        获取Kubernetes配置
        """
        queryset = self.queryset.get(pk=pk)
        try:
            k8s_config = json.loads(queryset.config)
            return Response({'data': k8s_config, 'status': 'success', 'code': 20000})
        except BaseException as e:
            logger.exception(f"Kubernetes [{queryset.name}] 配置异常.")
            return Response({'message': f'Kubernetes配置异常，请联系运维！', 'status': 'failed', 'code': 50000})

    @action(methods=['GET'], url_path='info', detail=True)
    def get_kubernetes_info(self, request, pk=None):
        info_type = request.query_params.get('type')
        namespaces = request.query_params.getlist('namespaces[]', None)
        service = request.query_params.get('service', None)
        service_filter = request.query_params.get('filter', False)
        _force = request.query_params.get('force', None)
        limit = request.query_params.get('limit', None)
        _continue = request.query_params.get('_continue', None)
        queryset = self.queryset.get(pk=pk)
        try:
            k8s_config = json.loads(queryset.config)
            cli = k8s_cli(queryset, k8s_config)
            if not cli[0]:
                logger.error(
                    f"Kubernetes [{queryset.name}] 配置异常，请联系运维: {cli[1]}！")
                return Response(
                    {'message': f'Kubernetes配置异常，请联系运维: {cli[1]}！', 'status': 'failed', 'code': 50000})
            cli = cli[1]
        except BaseException as e:
            logger.error(f"Kubernetes [{queryset.name}] 配置异常，请联系运维: {str(e)}！")
            return Response({'message': e, 'status': 'failed', 'code': 50000})
        ret = False
        if not ret or _force:
            kw = {}

            if limit:
                kw['limit'] = limit
            if _continue:
                kw['_continue'] = _continue
            if service_filter:
                kw['label_selector'] = f'app={service}'

            if info_type == 'nodes':
                ret = cli.get_nodes(**kw)
            elif info_type == 'namespaces':
                ret = cli.get_namespaces(**kw)
            elif info_type == 'services':
                ret = cli.get_services(namespaces[0], **kw)
            elif info_type == 'deployments':
                logger.debug(f'deployments kwargs === {kw}')
                ret = cli.get_namespace_deployment(
                    namespaces[0], queryset.version.get('apiversion', 'apps/v1'), **kw)
            elif info_type == 'deployment_info':
                ret = cli.fetch_deployment(
                    service, namespaces[0], queryset.version.get('apiversion', 'apps/v1'))
                ret = ret['message']
            elif info_type == 'service_info':
                ret = cli.fetch_service(
                    service, namespaces[0], queryset.version.get('apiversion', 'apps/v1'))
                ret = ret['message']
            elif info_type == 'deployment_pods':
                selectd = {"label_selector": f"app={service}"}
                ret = cli.get_pods(namespaces[0], **selectd)
                ret = ret['message']
            elif info_type == 'pods':
                ret = {'items': [], 'metadata': {}}
                ns_continue = []
                for ns in namespaces:
                    r = cli.get_pods(ns, **kw)
                    r = r['message']
                    if r['metadata'].get('continue', None):
                        ns_continue.append(r['metadata']['continue'])
                    try:
                        ret['items'].extend(r['items'])
                    except BaseException as e:
                        print('except: ', str(e))
                if ns_continue:
                    ret['metadata']['continue'] = ns_continue[0]
            elif info_type == 'configmap':
                ret = cli.get_configmaps(namespaces[0], **kw)
        try:
            if ret.get('items'):
                for i in ret['items']:
                    logger.debug(f'name == {i["metadata"]["name"]}')
                items = []
                for i in ret['items']:
                    name = i["metadata"]["name"]
                    if cache.get(f'wait-delete-k8s-resource:{info_type}:{name}') or cache.get(
                            f'wait-delete-k8s-resource:{info_type[0:-1]}:{name}'):
                        continue
                    items.append(i)
                ret['items'] = items
            return Response({'data': ret, 'status': 'success', 'code': 20000})
        except BaseException as e:
            logger.info(f'获取资源失败，返回内容{ret}，原因：{e}')
            return Response({'code': 50000, 'message': f'{str(e)}，{ret}'})

    @action(methods=['POST'], url_path='resource/manage', detail=True)
    def create_resource(self, request, pk=None):
        name = request.data.get('name', None)
        resource = request.data.get('resource', None)
        namespace = request.data.get('namespace', 'default')
        queryset = self.queryset.get(pk=pk)
        try:
            k8s_config = json.loads(queryset.config)
            cli = k8s_cli(queryset, k8s_config)
            if not cli[0]:
                logger.error(
                    f"Kubernetes [{queryset.name}] 配置异常，请联系运维: {cli[1]}！")
                return Response(
                    {'message': f'Kubernetes配置异常，请联系运维: {cli[1]}！', 'status': 'failed', 'code': 50000})
            cli = cli[1]
        except BaseException as e:
            return Response({'message': '未获取到配置', 'status': 'failed', 'code': 50000})

        ret = {'error': 1}
        if resource == 'namespace':
            ret = cli.create_namespace(name)
        elif resource == 'deployment':
            image = request.data.get('image', None)
            port = request.data.get('port')
            service_enable = request.data.get('service_enable', None)
            target_port = request.data.get('target_port', None)
            replicas = request.data.get('replicas', 1)
            ret = cli.create_namespace_deployment(
                name, image, port, replicas, namespace=namespace)
            if service_enable and len(target_port):
                resp = cli.create_namespace_service(
                    name, name, target_port, namespace)
                if resp.status == 409:
                    resp = cli.create_namespace_service(f"{name}-{datetime.now().strftime('%Y%m%d%H%M%S')}", name,
                                                        target_port, namespace)
                if isinstance(resp.status, int):
                    if not 200 <= resp.status <= 299:
                        ret = json.loads(resp.body)
                        return Response({'message': ret, 'status': 'failed', 'code': 20000})
                ret = f"服务名：{resp.metadata.name}"
        elif resource in ['service', 'services']:
            target_port = request.data.get('target_port', None)
            yaml_data = request.data.get('yaml', '')
            ret = cli.create_namespace_service(
                name, name, target_port, namespace, svc_yaml=yaml_data)
            status = ret.get('status')
            if status == 409:
                ret = cli.create_namespace_service(
                    f"{name}-{datetime.now().strftime('%Y%m%d%H%M%S')}",
                    name,
                    target_port, namespace
                )
        elif resource == 'configmap':
            yaml_data = request.data.get('yaml', '')
            ret = cli.create_namespace_configmap(yaml_data, namespace)
        else:
            return Response({
                'message': f'不支持的资源类型 {resource}',
                'status': 'success',
                'code': 20000
            })

        if ret.get('error'):
            return Response({
                'message': ret,
                'status': 'failed',
                'code': 40000
            })
        return Response({'data': ret, 'status': 'success', 'code': 20000})

    @action(methods=['PUT'], url_path='resource/patch', detail=True)
    @appinfo_order_check('put')
    def patch_resource(self, request, pk=None):
        name = request.data.get('name', None)
        namespace = request.data.get('namespace', 'default')
        resource = request.data.get('resource')
        action = request.data.get('type')
        queryset = self.queryset.get(pk=pk)
        try:
            k8s_config = json.loads(queryset.config)
            cli = k8s_cli(queryset, k8s_config)
            if not cli[0]:
                logger.error(
                    f"Kubernetes [{queryset.name}] 配置异常，请联系运维: {cli[1]}！")
                return Response(
                    {'message': f'Kubernetes配置异常，请联系运维: {cli[1]}！', 'status': 'failed', 'code': 50000})
            cli = cli[1]
        except BaseException as e:
            return Response({'message': '未获取到配置', 'status': 'failed', 'code': 50000})
        ret = {'err': 1}

        if resource == 'deployment':
            if action == 0:
                # 副本伸缩
                replicas = request.data.get('replicas', 1)
                ret = cli.update_deployment_replica(name, replicas, namespace)
                # 副本伸缩之后， 将副本数量更新到相应的应用数据中
                if '-' in namespace:
                    env_name, _ = namespace.split('-', 1)
                    micro_app_obj = MicroApp.objects.filter(name=name)
                    if micro_app_obj:
                        micro_app_obj = micro_app_obj.first()
                        uniq_tag = f'{micro_app_obj.appid}.{env_name}'
                        appinfo_obj = AppInfo.objects.filter(uniq_tag=uniq_tag)
                        if appinfo_obj:
                            appinfo_obj = appinfo_obj.first()
                            k8s_template = appinfo_obj.template
                            if k8s_template:
                                strategy = k8s_template.get('strategy', None)
                                if not strategy:
                                    k8s_template['strategy'] = {'data': [
                                        {'key': 'replicas',
                                         'type': 'inputNumber',
                                         'label': '副本',
                                         'value': 1,
                                         'inherit': 1,
                                         'restore': 1},
                                        {'key': 'revisionHistoryLimit',
                                         'type': 'inputNumber',
                                         'label': '保留副本',
                                         'value': 1,
                                         'inherit': 1,
                                         'restore': 1},
                                        {'key': 'minReadySeconds',
                                         'type': 'inputNumber',
                                         'label': '更新等待时间',
                                         'value': 3,
                                         'inherit': 3,
                                         'restore': 3},
                                        {'key': 'maxSurge',
                                         'slot': '%',
                                         'type': 'input',
                                         'label': '比例缩放/maxSurge',
                                         'value': '100',
                                         'inherit': '100',
                                         'restore': '100'},
                                        {'key': 'maxUnavailable',
                                         'slot': '%',
                                         'type': 'input',
                                         'label': '比例缩放/maxUnavailable',
                                         'value': '50',
                                         'inherit': '50',
                                         'restore': '50'}
                                    ],
                                        'custom': True}
                                else:
                                    strategy['custom'] = True
                                    for r in strategy['data']:
                                        if r['key'] == 'replicas':
                                            r['value'] = replicas
                                appinfo_obj.save()
                            else:
                                logger.warning(
                                    f'副本伸缩 uniq_tag： {uniq_tag} 不存在 template 字段 跳过执行')
                        else:
                            logger.warning(
                                f'副本伸缩 AppInfo 匹配不到 uniq_tag 数据： {uniq_tag} 跳过执行')
                    else:
                        logger.warning(
                            f'副本伸缩 MicroApp 匹配不到 name 数据： {name}  跳过执行')
            elif action == 1:
                # 更新镜像,不更新环境变量
                image = request.data.get('image')
                ret = cli.update_deployment_image(name, image, namespace)
            elif action == 2:
                ret = cli.restart_deployment(name, namespace)
            elif action == 3:
                # TODO: 删除环境变量
                # 抽屉详情页提交更新：资源限制、环境变量、镜像拉取策略
                envs = request.data.get('envs')
                envs = [env for env in envs if env['name']]
                image_policy = request.data.get('image_policy')
                cpu = request.data.get('cpu')
                memory = request.data.get('memory')
                resource = {'resources': {
                    'limits': {'cpu': cpu, 'memory': memory}}}
                ret = cli.update_deployment_resource(
                    name, envs, image_policy, namespace, **resource)
            elif action == 9:
                # 接收整个yaml文件进行deployment更新
                deploy_yaml = request.data.get('yaml')
                ret = cli.update_deployment(
                    name, deploy_yaml=deploy_yaml, namespace=namespace)
            else:
                return Response({
                    'code': 40000,
                    'status': 'failed',
                    'message': '不支持的 action 参数',
                })
        elif resource == 'service' or resource == 'services':
            if action == 0:
                target_port = request.data.get('target_port', None)
                ret = cli.update_namespace_service(
                    name, target_port, namespace)
            elif action == 1:
                svc_yaml = request.data.get('yaml')
                ret = cli.update_namespace_configmap(
                    name, namespace=namespace, svc_yaml=svc_yaml)
            else:
                return Response({
                    'code': 40000,
                    'status': 'failed',
                    'message': '不支持的 type 参数',
                })
        elif resource == 'configmap':
            yaml_data = request.data.get('yaml', '')
            ret = cli.update_namespace_configmap(name, yaml_data, namespace)
        else:
            return Response({
                'code': 40000,
                'status': 'failed',
                'message': '不支持的 resource 参数',
            })
        if ret.get('error'):
            return Response({'message': ret, 'status': 'failed', 'code': 40000})
        return Response({'data': ret, 'status': 'success', 'code': 20000})

    @action(methods=['DELETE'], url_path='resource/delete', detail=True)
    @appinfo_order_check('get')
    def delete_resource(self, request, pk=None):
        appinfo_id = request.query_params.get('appinfo_id', None)
        name = request.query_params.get('name', None)
        namespace = request.query_params.get('namespace', 'default')
        resource = request.query_params.get('resource')
        queryset = self.queryset.get(pk=pk)
        if resource not in ['deployment', 'service', 'services', 'configmap']:
            return Response({
                'message': f'不支持的资源类型 {resource}',
                'status': 'failed',
                'code': 40000
            })
        # 设定N分钟后删除
        countdown = int(request.query_params.get('countdown', 10))
        dkey = f'wait-delete-k8s-resource:{queryset.id}:{namespace}:{resource}:{name}'
        try:
            # 标记应用下线
            appinfo_obj = AppInfo.objects.get(id=appinfo_id)
            appinfo_obj.online = 10
            appinfo_obj.save()
            KubernetesDeploy.objects.filter(
                appinfo_id=appinfo_obj.id, kubernetes_id=pk).update(online=10)
        except BaseException as e:
            logger.exception(f'获取应用模块异常，原因：{e}')
        if countdown:
            if cache.get(dkey):
                return Response({'code': 40300, 'message': '应用删除已提交到后台，请勿重新提交！'})
            task = schedule('qtasks.tasks.k8s_resource_delete',
                            *[],
                            **{'config': queryset.config, 'resource': resource, 'apiversion': queryset.version.get('apiversion', 'apps/v1'), 'cluster_id': pk, 'app_name': name, 'namespace': namespace},
                            schedule_type=Schedule.ONCE,
                            next_run=datetime.now() + timedelta(minutes=countdown)
                            )
            cache.set(dkey, task.id, timeout=countdown * 60)
            message = f'操作已提交到任务后台，将在 {countdown} 分钟后执行[{task.id}]！'
        else:
            task = async_task('qtasks.tasks.k8s_resource_delete',
                              *[],
                              **{'config': queryset.config, 'resource': resource, 'apiversion': queryset.version.get('apiversion', 'apps/v1'), 'cluster_id': pk, 'app_name': name, 'namespace': namespace}
                              )
            if result(task, wait=500):
                message = '删除成功'
            message = '删除成功'
        return Response({'message': message, 'status': 'success', 'code': 20000})


class ProjectConfigViewSet(CustomModelViewSet):
    """
    项目视图

    ### 项目权限
        {'*': ('project_all', '项目管理')},
        {'get': ('project_list', '查看项目')},
        {'post': ('project_create', '创建项目')},
        {'put': ('project_edit', '编辑项目')},
        {'patch': ('project_edit', '编辑项目')},
        {'delete': ('project_delete', '删除项目')}
    """
    perms_map = (
        {'*': ('admin', '管理员')},
        {'*': ('project_all', '项目管理')},
        {'get': ('project_list', '查看项目')},
        {'post': ('project_create', '创建项目')},
        {'put': ('project_edit', '编辑项目')},
        {'patch': ('project_edit', '编辑项目')},
        {'delete': ('project_delete', '删除项目')}
    )
    queryset = ProjectConfig.objects.all()
    serializer_class = ProjectConfigSerializers
    filter_backends = (django_filters.rest_framework.DjangoFilterBackend,
                       CustomSearchFilter, OrderingFilter)
    filter_fields = ('project', 'environment',)
    search_fields = ('project', 'environment',)

    @action(methods=['GET'], url_path='template/inherit', detail=False)
    def get_inherit_template(self, request, *args, **kwargs):
        """
        获取可继承的模板配置
        """
        environment = request.query_params.get('environment', None)
        if not environment:
            return Response({'message': '缺少环境参数！', 'code': 50000})
        envInfo = Environment.objects.get(id=environment)
        for k, v in envInfo.template.items():
            if v and isinstance(v, (dict,)):
                v['custom'] = False
        return Response({'data': envInfo.template or {}, 'code': 20000})


class ProjectViewSet(CustomModelParentViewSet):
    """
    项目视图

    ### 项目权限
        {'*': ('project_all', '项目管理')},
        {'get': ('project_list', '查看项目')},
        {'post': ('project_create', '创建项目')},
        {'put': ('project_edit', '编辑项目')},
        {'patch': ('project_edit', '编辑项目')},
        {'delete': ('project_delete', '删除项目')}
    """
    perms_map = (
        {'*': ('admin', '管理员')},
        {'*': ('project_all', '项目管理')},
        {'get': ('project_list', '查看项目')},
        {'post': ('project_create', '创建项目')},
        {'put': ('project_edit', '编辑项目')},
        {'patch': ('project_edit', '编辑项目')},
        {'delete': ('project_delete', '删除项目')}
    )
    queryset = Project.objects.all()
    serializer_class = ProjectSerializers
    filter_backends = (django_filters.rest_framework.DjangoFilterBackend,
                       CustomSearchFilter, OrderingFilter)
    filter_fields = ('name', 'alias', 'product', 'product__name')
    search_fields = ('name', 'alias', 'product__name',)

    def extend_filter(self, queryset):
        perms = self.get_permission_from_role(self.request)
        return queryset

    def get_serializer_class(self):
        if self.action in ['list', 'retrieve']:
            return ProjectListSerializers
        else:
            return ProjectSerializers

    def perform_create(self, serializer):
        serializer.save(creator=self.request.user)

    @action(methods=['GET'], url_path='robot', detail=False)
    def get_robot(self, request):
        """
        获取项目机器人列表

        ### 传递参数
        """
        robots = SystemConfig.objects.filter(type='robot')
        data = []
        for i in robots:
            try:
                robot_type = json.loads(i.config)['type']
            except:
                robot_type = 'dingtalk'
            data.append({'id': i.id, 'name': i.name, 'robot_type': robot_type})
        return Response({'code': 20000, 'data': data})

    @action(methods=['GET', 'POST'], url_path='release_config', detail=True)
    def release_config(self, request, pk):
        release_configs = ProjectEnvReleaseConfig.objects.filter(
            project__id=pk)
        if request.method.lower() == 'get':
            environment_id = request.query_params['environment']
            release_configs = release_configs.filter(
                environment__id=environment_id)
            data_items = release_configs and ProjectEnvReleaseConfigSerializers(
                release_configs.first()).data or None
            return Response({
                'code': 20000,
                'status': 'success',
                'data': data_items
            })

        environment_id = request.data['environment']
        form = request.data['form']
        ProjectEnvReleaseConfig.objects.update_or_create(
            project_id=pk, environment_id=environment_id, defaults={'config': form})
        return Response({
            'code': 20000,
            'status': 'success',
            'message': '设置成功'
        })


class MicroAppViewSet(CustomModelViewSet):
    """
    项目应用视图

    ### 项目应用权限
        {'*': ('microapp_all', '应用管理')},
        {'get': ('microapp_list', '查看应用')},
        {'post': ('microapp_create', '创建应用')},
        {'put': ('microapp_edit', '编辑应用')},
        {'patch': ('microapp_edit', '编辑应用')},
        {'delete': ('microapp_delete', '删除应用')}
    """
    perms_map = (
        {'*': ('admin', '管理员')},
        {'*': ('microapp_all', '应用管理')},
        {'get': ('microapp_list', '查看应用')},
        {'post': ('microapp_create', '创建应用')},
        {'put': ('microapp_edit', '编辑应用')},
        {'patch': ('microapp_edit', '编辑应用')},
        {'delete': ('microapp_delete', '删除应用')}
    )
    queryset = MicroApp.objects.all()
    serializer_class = MicroAppSerializers
    permission_classes = [IsAuthenticated, AppPermission, RbacPermission]
    filter_backends = (django_filters.rest_framework.DjangoFilterBackend,
                       CustomSearchFilter, OrderingFilter)
    filter_fields = ('category', 'name', 'alias',
                     'project__product_id', 'project_id')
    search_fields = ('category', 'name', 'alias', 'language', 'appid')

    def create(self, request, *args, **kwargs):
        """
        创建应用

        提交参数
        批量创建:[{},{}...]
        创建：{}
        """
        if isinstance(request.data, list):
            for data in request.data:
                try:
                    data['name'] = data['name'].strip(' ').replace(' ', '-')
                except BaseException as e:
                    print('exception ', str(e))

            serializer = self.get_serializer(data=request.data, many=True)
        else:
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

    def extend_filter(self, queryset):
        return queryset

    def get_serializer_class(self):
        if self.action in ['list', 'retrieve']:
            return MicroAppListSerializers
        if self.action in ['perm_app', 'perm_apply']:
            return MicroAppListForPermApplySerializers
        return MicroAppSerializers

    @transaction.atomic
    def perform_create(self, serializer):
        serializer.save(creator=self.request.user)

        if isinstance(serializer.data, list):
            for data in serializer.data:
                try:
                    self.appinfo_create(data)
                except BaseException as e:
                    logger.error(f'创建应用失败, 原因: {e}')
        else:
            try:
                self.appinfo_create(serializer.data)
            except BaseException as e:
                logger.error(f'创建应用失败, 原因: {e}')

    def extend_jenkins(self, data, env):
        appinfo_obj = AppInfo.objects.filter(id=data['id']).first()
        JENKINS_CONFIG = get_redis_data('cicd-jenkins')
        jbuild = JenkinsBuild(JENKINS_CONFIG['url'], username=JENKINS_CONFIG['user'],
                              password=JENKINS_CONFIG['password'],
                              job_id=0, appinfo_id=appinfo_obj.id, job_type='app')
        try:
            jbuild.create_view(appinfo_obj, env)
        except BaseException as e:
            pass
        try:
            ok, msg = jbuild.create(
                jenkinsfile=f'{appinfo_obj.app.language}/Jenkinsfile', desc=appinfo_obj.app.alias)
            if not ok:
                logger.error(f'创建jenkins任务失败，原因：{msg}')
        except Exception as err:
            logger.error(
                f'创建应用[{appinfo_obj.uniq_tag}]的Jenkins任务失败, 原因: {err}')
            log_audit(self.request, self.serializer_class.Meta.model.__name__, f'创建Jenkins任务失败',
                      f"任务名称{appinfo_obj.jenkins_jobname}")

    def appinfo_create(self, data):
        # 自动创建不同环境的应用服务
        envs = Environment.objects.all()
        try:
            _language = DevLanguage.objects.get(name=data['language'])
        except BaseException as e:
            raise Exception(f'获取开发语言失败, 原因: {e}')
        _project = Project.objects.get(id=data['project'])
        # 读取预设数据
        try:
            _config = DataDict.objects.get(
                key=f"config.{_project.product.name}").extra
            _config = json.loads(_config)
        except BaseException as e:
            raise Exception(f'读取应用预设数据失败, 原因: {e}')
        for env in envs:
            if env.name in _config:
                _hosts = []
                _kubernetes = []
                try:
                    _build = _language.build['build'] if _language.build['type'] == 0 else \
                        [i['value'] for i in _language.build['env']
                            if i['name'] == env.id][0]
                    if data['category'] == 'category.server':
                        # 后端
                        _kubernetes = [i.id for i in KubernetesCluster.objects.filter(
                            name__in=_config[env.name]['category'].get(data['category'].split('.')[-1], []))]
                    else:
                        _hosts = _config[env.name]['category'].get(
                            data['category'].split('.')[-1], [])
                except BaseException as e:
                    _build = ''
                    raise Exception(f'获取配置失败, 原因: {e}')
                _data = {
                    'uniq_tag': 'default',
                    # 'apollo': 0,
                    'app': data['id'],
                    'branch': _config[env.name]['git_branch'],
                    'build_command': _build,
                    'environment': env.id,
                    'template': data['template'],
                    'hosts': _hosts,
                    'kubernetes': _kubernetes
                }
                serializer = AppInfoSerializers(data=_data)
                try:
                    appinfo = AppInfo.objects.get(
                        uniq_tag=f"{data['appid']}.{env.name.lower()}")
                    _data['id'] = appinfo.id
                    _data['uniq_tag'] = appinfo.uniq_tag
                    serializer = AppInfoSerializers(appinfo, data=_data)
                except BaseException as e:
                    pass
                serializer.is_valid(raise_exception=True)
                serializer.save()
                _data = serializer.data
                self.extend_jenkins(_data, env)

    @action(methods=['POST'], url_path='related', detail=False)
    def app_related(self, request):
        """
        应用关联

        ### 传递参数:
            ids: 待关联应用id数组
            target: 目标应用id
        """
        try:
            target = request.data.get('target', None)
            ids = request.data.get('ids', None)
            if target:
                instance = self.queryset.get(id=target)
                ids.extend(instance.multiple_ids)
            self.queryset.filter(id__in=list(set(ids))).update(
                multiple_app=True, multiple_ids=list(set(ids)))
            return Response({'code': 20000, 'data': '应用关联成功.'})
        except BaseException as e:
            print('err', e)
            return Response({'code': 50000, 'data': '关联应用异常,请联系管理员!'})

    @action(methods=['POST'], url_path='unrelated', detail=False)
    def app_unrelated(self, request):
        """
        取消应用关联

        ### 传递参数:
            id: 应用id
        """
        try:
            instance = self.queryset.filter(id=request.data.get('id'))
            # 获取关联应用ID列表
            ids = instance[0].multiple_ids
            ids.remove(instance[0].id)
            if len(ids) == 1:
                # 如果关联应用只剩下一个,则一起取消关联
                self.queryset.filter(id__in=instance[0].multiple_ids).update(
                    multiple_app=False, multiple_ids=[])
            else:
                # 更新其它应用的关联应用ID
                self.queryset.filter(id__in=ids).update(multiple_ids=ids)
                # 取消当前实例应用关联
                instance.update(multiple_app=False, multiple_ids=[])
            return Response({'code': 20000, 'data': '应用取消关联成功.'})
        except BaseException as e:
            return Response({'code': 50000, 'data': '关联应用异常,请联系管理员!'})

    @action(methods=['put'], url_path='members', detail=True, perms_map=({'put': ('members_edit', '团队管理')},))
    @transaction.atomic
    def team_members(self, request, pk=None):
        """
        ### 团队成员管理权限
            {'put': ('members_edit', '团队管理')},
        """
        queryset = self.queryset.get(id=pk)
        operator_id = [queryset.creator and queryset.creator.id]
        if queryset.project:
            if queryset.project.creator:
                operator_id.append(queryset.project.creator.id)
            if queryset.project.manager:
                operator_id.append(queryset.project.developer)
        perms = get_permission_from_role(request)
        if not request.user.is_superuser and 'admin' not in perms and request.user.id not in operator_id:
            return Response({'code': 50000, 'message': '无权限操作！'})
        if request.data.get('id', None):
            request.data.pop('id')
        return Response({'code': 50000, 'message': '非法操作！'})

    @action(methods=['GET'], url_path='git/repos', detail=False)
    def get_repository(self, request):
        """
        获取仓库项目

        ### 获取仓库项目权限
            {'get': ('repo_list', '获取仓库项目')}
        """
        page_size = request.query_params.get('page_size', 20)
        page = request.query_params.get('page', 1)
        _repo = request.query_params.get('repo', None)  # 搜索仓库
        repos = request.query_params.getlist('repos[]', [])  # 仓库列表
        repo_ids = request.query_params.getlist('repo_ids[]', [])
        ok, cli = gitlab_cli(admin=True)
        if ok is False:
            return Response({'code': 50000, 'message': cli})
        try:
            # 对搜索词进行处理，只获取project name部分
            params = {'page': page, 'per_page': page_size}
            if _repo:
                params['key'] = _repo.split('/')[-1].rstrip('.git')
            projects = cli.list_projects(**params)
            for i in repo_ids:
                if int(i) not in [j.id for j in projects]:
                    # 不存在列表
                    _project = cli.get_project(project_id=i)
                    if _project:
                        projects.insert(0, _project)
            data = [{'id': i.id, 'name': i.name, 'description': i.description, 'path_with_namespace': i.path_with_namespace,
                     'http_url_to_repo': i.http_url_to_repo} for i in projects]
            return Response({'code': 20000, 'data': data})
        except BaseException as e:
            logger.debug(f'获取仓库项目失败, 原因: {str(e)}')
            return Response({'code': 50000, 'message': str(e)})

    @action(methods=['GET'], url_path='git/groups', detail=False)
    def get_git_groups(self, request):
        """
        获取git组
        """
        group_id = request.query_params.get('group_id', None)
        group_detail = request.query_params.get('detail', None)
        ok, cli = gitlab_cli(superadmin=True)
        if ok is False:
            return Response({'code': 50000, 'message': cli})
        try:
            if group_id:
                group = cli.get_gl().groups.get(group_id)
                if group_detail:
                    return Response({'code': 20000, 'data': {'id': group.id, 'name': group.name, 'description': group.description}})
                data = [{'id': i.id, 'name': i.name, 'description': i.description}
                        for i in group.subgroups.list()]
                return Response({'code': 20000, 'data': {'items': data}})
            data = cli.list_groups(get_all=True, per_page=100)
            return Response({'code': 20000, 'data': {'items': data}})
        except BaseException as e:
            logger.error(f'获取项目仓库分支失败, 原因: {e}')
            return Response({'code': 50000, 'message': str(e)})

    @action(methods=['GET'], url_path='git/repo/branches', detail=False)
    def get_branches(self, request):
        """
        获取仓库项目分支

        ### 获取仓库项目分支权限
            {'get': ('repo_list', '获取仓库项目')}
        """
        _branch = request.query_params.get('branch', None)
        project_name = request.query_params.get('project_name', None)
        project_id = request.query_params.get('project_id')
        project_type = request.query_params.get('type', None)
        protected = request.query_params.get(
            'protected', '0')  # 0: 所有, 1: 受保护, 2：不受保护
        ok, cli = gitlab_cli(admin=True)
        if ok is False:
            return Response({'code': 50000, 'message': cli})
        try:
            if project_type == 'tag':
                data = cli.list_tags(
                    project_id=project_id, get_all=True)
                return Response({'code': 20000, 'data': data})
            if project_type == 'branch':
                data = cli.list_branches(project_id=project_id, get_all=True,
                                         key=_branch, protected=protected)
                return Response({'code': 20000, 'data': data})
            data = [{'label': G_COMMIT[0][1],
                     'options': cli.list_branches(project_id=project_id, get_all=True, key=_branch, protected=protected)},
                    {'label': G_COMMIT[1][1],
                     'options': cli.list_tags(project_id=project_id, get_all=True)}]
            return Response({'code': 20000, 'data': data})
        except BaseException as e:
            logger.error(f'获取项目仓库分支失败, 原因: {e}')
            return Response({'code': 50000, 'message': str(e)})

    @action(methods=['GET'], url_path='harbor/search', detail=False)
    def search_harbor(self, request):
        """
        搜索harbor镜像
        """
        query = request.query_params.get('query', '')
        harbor_config = get_redis_data('cicd-harbor')
        cli = HarborAPI(url=harbor_config['url'], username=harbor_config['user'],
                        password=harbor_config['password'])
        data = cli.search(query)
        if data.get('ecode', 200) > 399:
            return Response({'code': 50000, 'status': 'failed', 'message': data['message']})
        return Response({'code': 20000, 'data': data['data']['repository']})

    @action(methods=['GET'], url_path='harbor', detail=False)
    def get_harbor(self, request):
        """
        获取Harbor仓库镜像

        ### Return
            [
                {
                "name": "143_20210713175812_227c275b",
                "created": "2021-07-13T09:59:09.074315572Z",
                "push_time": null,
                "size": 186171490
                }
            ]
        """
        harbor_config = get_redis_data('cicd-harbor')
        cli = HarborAPI(url=harbor_config['url'], username=harbor_config['user'],
                        password=harbor_config['password'])
        req_type = request.query_params.get('type', None)
        image = request.query_params.get('image', None)
        project_id = request.query_params.get('project_id', None)
        query = request.query_params.get('search', None)
        if req_type == 'projects':
            data = cli.get_projects(project_name=query)
            if data.get('ecode', 200) > 399:
                logger.error(f"获取Harbor仓库项目失败, 原因: {data['message']}")
                return Response({'code': 50000, 'status': 'failed', 'message': data['message']})
            return Response({'code': 20000, 'data': data['data']})
        if req_type == 'project_info':
            data = cli.fetch_project(project_id=project_id)
            if data.get('ecode', 200) > 399:
                logger.error(f"获取Harbor仓库项目信息失败, 原因: {data['message']}")
                return Response({'code': 50000, 'status': 'failed', 'message': data['message']})
            return Response({'code': 20000, 'data': data['data']})
        if req_type == 'repos':
            data = cli.get_repositories(project_id, repo=query)
            if data.get('ecode', 200) > 399:
                logger.error(f"获取Harbor仓库镜像失败, 原因: {data['message']}")
                return Response({'code': 50000, 'status': 'failed', 'message': data['message']})
            return Response({'code': 20000, 'data': data['data']})
        if req_type == 'tags':
            data = cli.get_tags(image)
            if data.get('ecode', 200) > 399:
                logger.error(f"获取Harbor仓库镜像标签失败, 原因: {data['message']}")
                return Response({'code': 50000, 'status': 'failed', 'message': data['message']})
            return Response({'code': 20000, 'data': data['data']})
        return Response({'code': 50000, 'status': 'failed', 'message': '非法请求!'})

    @action(methods=['POST'], url_path='check', detail=False)
    def check_app(self, request, *args, **kwargs):
        """
        检测应用是否存在
        """
        name = request.data.get('name', None)
        product_with_project = request.data.get('product_with_project', None)
        if all([name, product_with_project]) is False:
            return Response({'code': 50000, 'message': '缺少参数！'})
        qs = self.queryset.filter(
            name=name, project_id=product_with_project[1])
        if qs:
            return Response({'code': 40300, 'message': '当前项目已存在相同的应用名！'})
        return Response({'code': 20000})

    def destroy(self, request, *args, **kwargs):
        """
        TODO: 删除操作物理删除 or 逻辑删除(增加删除标记字段)
        有关联的应用模块允许删除操作
        """
        instance = self.get_object()
        try:
            AppInfo.objects.filter(app_id=instance.id).delete()
            self.perform_destroy(instance)
        except BaseException as e:
            return Response({'code': 50000, 'status': 'failed', 'message': f'删除异常： {str(e)}'})
        log_audit(request, self.serializer_class.Meta.model.__name__,
                  '删除', content=f"删除对象：{instance}")

        return Response({'code': 20000, 'status': 'success', 'msg': ''})


class AppInfoViewSet(CustomModelViewSet):
    """
    项目应用服务

    * 服务对应着应用的不同环境，即应用每个环境创建一个对应的服务

    ### 项目应用服务权限
        {'*': ('appinfo_all', '应用模块管理')},
        {'get': ('appinfo_list', '查看应用模块')},
        {'post': ('appinfo_create', '创建应用模块')},
        {'put': ('appinfo_edit', '编辑应用模块')},
        {'patch': ('appinfo_edit', '编辑应用模块')},
        {'delete': ('appinfo_delete', '删除应用模块')}
    """
    perms_map = (
        {'*': ('admin', '管理员')},
        {'*': ('appinfo_all', '应用模块管理')},
        {'get': ('appinfo_list', '查看应用模块')},
        {'post': ('appinfo_create', '创建应用模块')},
        {'put': ('appinfo_edit', '编辑应用模块')},
        {'patch': ('appinfo_edit', '编辑应用模块')},
        {'delete': ('appinfo_delete', '删除应用模块')}
    )
    queryset = AppInfo.objects.all()
    serializer_class = AppInfoSerializers
    permission_classes = [IsAuthenticated, RbacPermission, AppInfoPermission]
    filter_backends = (django_filters.rest_framework.DjangoFilterBackend,
                       CustomSearchFilter)
    filter_fields = (
        'id', 'app_id', 'app__appid', 'environment', 'app__project_id',
        'app__project__product_id',
        'app__category')
    search_fields = ('app__appid', 'environment__name',
                     'app__name', 'app__alias')
    ordering_fields = ['update_time', 'created_time', 'status',
                       'deploy_type', 'last_build_time', 'last_build_status', 'last_deploy_time', 'last_deploy_status']

    def extra_select(self, queryset):
        if self.action in ['service_for_cd', 'service_for_ci'] and self.request.query_params.get('ordering', None):
            _models = {'service_for_ci': ['deploy_buildjob', 'last_build_time', 'last_build_status'],
                       'service_for_cd': ['deploy_deployjob', 'last_deploy_time', 'last_deploy_status']}
            for _, _map in _models.items():
                _sql = '''select FIELD from {0} where {0}.appinfo_id=cmdb_appinfo.id order by -id limit 1'''.format(
                    _map[0])
                queryset = queryset.extra(select={_map[1]: _sql.replace('FIELD', 'created_time'),
                                                  _map[2]: _sql.replace('FIELD', 'status')})
            return queryset
        return queryset

    def extend_filter(self, queryset):
        return self.extra_select(queryset)

    def get_serializer_class(self):
        if self.action in ['list', 'retrieve']:
            return AppInfoListSerializers
        if self.action == 'service_with_image':
            return AppInfoListForDeploySerializers
        if self.action == 'service_for_ci':
            return AppInfoListForCiSerializers
        if self.action == 'service_for_cd':
            return AppInfoListForCdSerializers
        if self.action == 'service_for_deploy':
            return AppInfoListForOrderSerializers
        return AppInfoSerializers

    def extend_jenkins(self, data, action_type='创建'):
        appinfo_obj = self.queryset.filter(app_id=data['app']).first()
        env = Environment.objects.get(
            pk=data['environment']) if action_type == '创建' else appinfo_obj.environment
        JENKINS_CONFIG = get_redis_data('cicd-jenkins')
        jbuild = JenkinsBuild(JENKINS_CONFIG['url'], username=JENKINS_CONFIG['user'],
                              password=JENKINS_CONFIG['password'], job_id=0, appinfo_id=appinfo_obj.id, job_type='app')
        try:
            jbuild.create_view(appinfo_obj, env)
        except BaseException as e:
            pass
        try:
            ok, msg = jbuild.create(
                jenkinsfile=f'{appinfo_obj.app.language}/Jenkinsfile', desc=appinfo_obj.app.alias)
            if not ok:
                logger.error(f'创建jenkins任务失败，原因：{msg}')
                return {'message': f'创建jenkins任务失败，原因：{msg}'}
        except Exception as err:
            log_audit(self.request, self.serializer_class.Meta.model.__name__, f'{action_type}Jenkins任务失败',
                      f"任务名称{appinfo_obj.jenkins_jobname}")
            return {"message": f"创建Jenkins JOB: {appinfo_obj.jenkins_jobname}  失败"}

    def create(self, request, *args, **kwargs):
        request.data['uniq_tag'] = 'default'
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        data = serializer.data

        ret = self.extend_jenkins(data, '创建')
        data = {'code': 20000, 'status': 200, 'data': data}
        if ret is not None:
            data['code'] = 50000
            data['message'] = ret['message']
        return Response(data)

    def perform_update(self, serializer):
        serializer.save()
        # 处理jenkins任务
        self.extend_jenkins(serializer.data, '更新')

    @action(methods=['GET'], url_path='template/inherit', detail=False)
    def get_inherit_template(self, request, *args, **kwargs):
        """
        获取可继承的模板配置
        :param environment: 环境ID
        :param app_id: 应用ID
        """
        env_id = request.query_params.get('environment', None)
        app_id = request.query_params.get('app_id', None)
        if not env_id or not app_id:
            return Response({'message': '缺少参数！', 'code': 50000})
        environment = Environment.objects.get(id=env_id)
        microapp = MicroApp.objects.get(id=app_id)
        project_config = ProjectConfig.objects.filter(
            project_id=microapp.project.id, environment_id=environment.id)
        # 模板优先级
        # 应用 -> 项目 -> 环境
        inheritTemplate = {}
        if project_config.first():
            for k, v in project_config.first().template.items():
                if v and isinstance(v, (dict,)):
                    if v.get('custom', False) is False:
                        # 继承
                        if environment.template.get(k, None):
                            inheritTemplate[k] = environment.template[k]
                    else:
                        if project_config.first().template.get(k, None):
                            inheritTemplate[k] = project_config.first(
                            ).template[k]
            # 继承多容器配置
            inheritTemplate['containers'] = project_config.first(
            ).template.get('containers', [])
        for k, v in microapp.template.items():
            if '_on' in k and v:
                # 应用层打开自定义开关
                _k = k.rstrip('_on')
                if microapp.template.get(_k, None):
                    inheritTemplate[_k] = microapp.template[_k]
        for k, v in inheritTemplate.items():
            if v and isinstance(v, (dict,)):
                v['custom'] = False
        return Response({'data': inheritTemplate, 'code': 20000})

    @action(methods=['GET'], detail=False, url_path='asset/search')
    def asset_search(self, request):
        """
        搜索资产
        """
        key_list = ['cloud_privateip', 'ip']
        search_config = get_datadict('cmdb.search_index', config=1,
                                     default_value={'index': ['idc_*', 'cloud_*'], 'key': key_list})
        search_key = request.query_params.get('search', None)
        if search_key:
            conditions = [EQ('wildcard', **{i: f'*{search_key}*'})
                          for i in search_config['key']]
            # 排除索引 -{index_name}
            qs = Search(prefix=True, index=search_config['index']).query(
                reduce(operator.or_, conditions))[0:1000]
        else:
            qs = Search(prefix=True, index=search_config['index']).query()[
                0:20]
        data = {}
        for i in qs:
            _data = i.to_dict()
            _temp = {'idc': _data.get('idc', None),
                     'instanceid': _data['instanceid']}
            for j in search_config['key']:
                if _data.get(j, None):
                    try:
                        _temp['ipaddr'] = '|'.join(_data[j]) if isinstance(
                            _data[j], (list,)) else _data[j]
                    except BaseException as e:
                        _temp['ipaddr'] = ''
            data[_data['instanceid']] = _temp
        return Response({'code': 20000, 'data': data.values()})

    @action(methods=['GET', 'PUT'], detail=True, url_path='editor')
    def app_editor(self, request, *args, **kwargs):
        """
        如果 指定了env ，操作的是 AppInfo.can_edit
        如果 没有指定了env ，操作的是 MicroApp.can_edit
        :param request:
        :return:
        """
        method = request.method.lower()
        pk = kwargs['pk']
        env = method == 'get' and request.GET.get(
            'env') or request.data.get('env')
        if env:
            instance = AppInfo.objects.filter(app_id=pk, environment_id=env)
            if instance.count() == 0:
                return Response({
                    'status': 'failed',
                    'code': 40000,
                    'message': '当前环境没有数据',
                })
            instance = instance.first()
        else:
            instance = MicroApp.objects.get(id=pk)

        if method == 'get':
            return Response({
                'status': 'success',
                'code': 20000,
                'data': {
                    'env': env,
                    'users': instance.can_edit,
                }
            })

        self.check_object_permissions(request, instance)

        user = request.data.get('user', [])
        instance.can_edit = user
        instance.save()
        return Response({
            'status': 'success',
            'code': 20000,
            'message': 'app 权限用户更新完毕',
        })

    @action(methods=['GET'], detail=True, url_path='version')
    def service_current_version(self, request, pk=None):
        """
        获取应用当前运行版本
        """
        module = request.query_params.get('module', None)
        deploy_jobs = DeployJob.objects.filter(appinfo_id=pk, status=1)
        if module:
            deploy_jobs = deploy_jobs.filter(modules=module.split(':')[-1])
        data = deploy_jobs.first()
        try:
            return Response({'code': 20000, 'data': {'appinfo_id': data.appinfo_id, 'image': data.image.split(':')[-1]}})
        except BaseException as e:
            return Response({'code': 50000, 'message': '获取运行版本失败.'})

    @action(methods=['GET'], detail=False, url_path='order/app')
    def service_for_deploy(self, request):
        return super().list(request)

    @action(methods=['GET'], detail=False, url_path='extra')
    def service_with_image(self, request):
        app_ids = request.query_params.getlist('ids[]', [])
        queryset = self.queryset.filter(id__in=app_ids)
        serializer = self.get_serializer(queryset, many=True)
        return Response(
            {'data': {'total': queryset.count(), 'items': serializer.data}, 'code': 20000, 'status': 'success'})

    @action(methods=['GET'], detail=False, url_path='ci')
    def service_for_ci(self, request):
        return super().list(request)

    @action(methods=['GET'], detail=False, url_path='cd')
    def service_for_cd(self, request):
        return super().list(request)

    @action(methods=['GET'], detail=True, url_path='preview')
    def yaml_preview(self, request, pk=None):
        """
        Kubernetes Deployment Yaml配置预览

        ### 参数 ?image={image}
        """
        image = request.query_params.get('image', None)
        appinfo_obj = self.queryset.get(pk=pk)
        if not image:
            image = f'{appinfo_obj.app.name}:4preview'
        data = template_generate(appinfo_obj, image)
        if data['ecode'] != 200:
            return Response({
                'status': 'failed',
                'message': f'生成yaml文件出错： {data["message"]}',
                'code': 40000
            })
        data['yaml'] = yaml.safe_dump(data['yaml'], default_flow_style=False)
        if 'apm_yaml' in data:
            data['apm_yaml'] = yaml.safe_dump(
                data['apm_yaml'], default_flow_style=False)
        return Response({'data': data, 'code': 20000})

    @action(methods=['GET'], url_path='pipeline', detail=True)
    def pipeline(self, request, *args, **kwargs):
        qs = self.get_object()
        return Response({'code': 20000, 'data': qs.pipeline})
