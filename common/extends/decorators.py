#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
@Author : Charles Lai
@Contact : qqing_lai@hotmail.com
@Time : 2021/12/24 下午3:32
@FileName: decorators.py
@Blog ：https://imaojia.com
"""
import datetime
import json
import logging
import time
from functools import wraps

from django.core.cache import cache
from rest_framework import status
from rest_framework.response import Response
from django.db.models import Q

from dbapp.models import AppInfo, MicroApp
from common.ext_fun import get_redis_data, k8s_cli, set_redis_data, template_generate, time_comp
from common.extends.permissions import RbacPermission
from deploy.ext_func import check_user_deploy_perm
from dbapp.models import BuildJob, PublishOrder
from dbapp.models import DataDict
from dbapp.models import Workflow

logger = logging.getLogger('drf')


def build_allow_check():
    """
    构建条件检查
    """

    def decorator(func):
        @wraps(func)
        def wrapper(self, request, *args, **kwargs):
            env = request.data.get('env', None)
            commits = request.data.get('commits', '')
            modules = request.data.get('modules', 'dist')
            # 强制构建
            force = request.data.get('force', False)
            # {0: 构建, 1: 构建发布}
            is_deploy = request.data.get('is_deploy', False)
            try:
                appinfo_obj = AppInfo.objects.get(
                    pk=kwargs['pk'], environment_id=env)
            except BaseException as e:
                logger.debug(f'获取应用模块失败：{e}')
                return Response({'code': 50000, 'message': '获取应用模块失败.'})

            if is_deploy:
                if all([appinfo_obj.environment.ticket_on, [appinfo_obj.app.project.product.region.name,
                                                            appinfo_obj.app.project.product.name] not in appinfo_obj.environment.extra.get(
                        'product', [])]):
                    # 启用工单且不在跳过产品列表的必须走发版申请
                    logger.info(
                        f'应用[{appinfo_obj.uniq_tag}]发版被拒绝, 原因: 该应用不允许直接发布,请提交发版申请!')
                    return Response({'code': 40300, 'message': '该应用不允许直接发布,请构建后提交发版申请!'})

            check_filter = {'appinfo_id': appinfo_obj.id,
                            'status': 1,
                            'commits__short_id': commits['short_id']}
            check_build_history = self.queryset.filter(**check_filter).count()
            if check_build_history and not force:
                logger.info(
                    f'应用[{appinfo_obj.uniq_tag}]构建失败, 原因: CommitID已构建成功，请勿重复构建！')
                return Response({'code': 40403, 'status': 'failed', 'message': '当前CommitID已构建成功，请勿重复构建！'})

            return func(self, request, *args, **kwargs)

        return wrapper

    return decorator


def deploy_allow_check(deploy_from):
    """
    发布权限检查
    """

    def decorator(func):
        @wraps(func)
        def wrapper(self, request, *args, **kwargs):
            order_id = request.data.get('order_id', None)
            appinfo_obj = AppInfo.objects.get(id=request.data['appinfo_id'])
            if not request.data.get('image', None):
                logger.info(f'应用[{appinfo_obj.uniq_tag}]发版失败, 原因: 未选择发布镜像!')
                return Response(data={'code': 40300, 'message': '未选择发布镜像!'}, status=status.HTTP_200_OK)

            perm_params = {
                'perms': None,
                'pub_order': None
            }

            if deploy_from == 'order':
                if not appinfo_obj.environment.ticket_on:
                    return Response(data={'code': 40300, 'message': f'当前应用 {appinfo_obj} 没有开启工单，请联系运维！'}, status=status.HTTP_200_OK)
                pub_order = PublishOrder.objects.get(order_id=order_id)
                perm_params['pub_order'] = pub_order
                publish_time_expire_conf = json.loads(
                    DataDict.objects.get(key='PUBLISH_TIME_DIFF').extra)
                if pub_order.status == 0 and time_comp(pub_order.expect_time, **publish_time_expire_conf) is False:
                    logger.info(
                        f'工单应用[{appinfo_obj.uniq_tag}]发版被拒绝, 原因: 发版时间已过， 设定的超时时间为 {publish_time_expire_conf}')
                    return Response(data={'code': 40300, 'message': '当前时间不允许发布, 请确认工单期望发版时间!'}, status=status.HTTP_200_OK)
            else:
                perm_params['perms'] = self.get_permission_from_role(request)
            # deployment yaml预检
            if appinfo_obj.app.category.split('.')[-1] == 'server' and appinfo_obj.app.is_k8s == 'k8s':
                deploy_yaml = template_generate(
                    appinfo_obj, request.data['image'], partial_deploy_replicas=request.data.get('partial_deploy_replicas', 0))
                if deploy_yaml.get('ecode', 500) != 200:
                    # k8s deployment模板生成失败返回False
                    logger.error(
                        {'code': 500, 'message': deploy_yaml['message']})
                    return Response(data={'code': 50000, 'message': f"Yaml生成异常，原因：{deploy_yaml['message']}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
            # 检查线上k8s的deployment是否存在
            k8s_deployment_stat = []
            namespace = appinfo_obj.namespace
            for k8s in appinfo_obj.kubernetes.all():
                api_version = k8s.version.get('apiversion', 'apps/v1')
                k8s_config = json.loads(k8s.config)
                cli = k8s_cli(k8s, k8s_config)
                if not cli[0]:
                    logger.error(
                        f"Kubernetes [{k8s.name}] 配置异常，请联系运维: {cli[1]}！")
                    return Response(data={'message': f"Kubernetes [{k8s.name}] 配置异常，请联系运维: {cli[1]}！", 'status': 'failed',
                                          'code': 50000}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
                cli = cli[1]
                check_deployment = cli.fetch_deployment(
                    appinfo_obj.app.name, namespace, api_version)
                if check_deployment.get('ecode', 200) > 399:
                    # deployment不存在
                    k8s_deployment_stat.append(0)
                else:
                    k8s_deployment_stat.append(1)

            return func(self, request, *args, **kwargs)

        return wrapper

    return decorator


def appinfo_order_check(reqMethod):
    """
    检查应用是否启用工单
    """

    def decorator(func):
        @wraps(func)
        def wrapper(self, request, *args, **kwargs):
            if reqMethod == 'get':
                appinfo_id = request.query_params.get('appinfo_id', None)
            else:
                appinfo_id = request.data.get('appinfo_id', None)
            appinfo_objs = AppInfo.objects.filter(id=appinfo_id)
            if not appinfo_objs:
                return Response(data={'code': 40400, 'message': f'操作被拒绝，原因：找不到应用.'})
            return func(self, request, *args, **kwargs)
        return wrapper

    return decorator


def branch_allow_check(view_type):
    """
    分支检查
    """
    type_map = {'ci': ['allow_ci_branch', '构建'], 'cd': ['allow_cd_branch', '发布'],
                'jenkins_callback': ['allow_cd_branch', '发布']}

    def check_branch(branch, allow_branch):
        if branch in allow_branch or '*' in allow_branch:
            return True
        for i in allow_branch:
            if branch.startswith(i.rstrip('-*')):
                return True
        return False

    def decorator(func):
        @wraps(func)
        def wrapper(self, request, *args, **kwargs):
            commit_tag = request.data.get('commit_tag', None)
            _status = status.HTTP_200_OK
            if not commit_tag or commit_tag.get('name', None) is None:
                if view_type == 'jenkins_callback':
                    logger.exception(f"Jenkins回调发布异常, 缺少参数commit_tag.")
                    _status = status.HTTP_500_INTERNAL_SERVER_ERROR
                return Response(data={'code': 50000, 'status': 'failed', 'message': '未获取到分支信息,请检查参数！'},
                                status=_status)
            if view_type == 'ci':
                appinfo_id = kwargs.get('pk', None)
            elif view_type == 'jenkins_callback':
                build_job = BuildJob.objects.get(id=request.data.get('jobid'))
                appinfo_id = build_job.appinfo_id
            else:
                appinfo_id = request.data.get('appinfo_id', None)
            appinfos = AppInfo.objects.filter(id=appinfo_id)
            if appinfos.count() < 1:
                logger.error(f"获取应用[ID: {appinfo_id}]失败, 原因: 应用环境未配置")
                if view_type == 'jenkins_callback':
                    _status = status.HTTP_404_NOT_FOUND
                return Response(data={'code': 50000, 'status': 'failed', 'message': '应用环境未配置！'},
                                status=_status)
            appinfo_obj = appinfos[0]
            allow_branch = getattr(appinfo_obj, type_map[view_type][0]) or getattr(appinfo_obj.environment,
                                                                                   type_map[view_type][0])
            if view_type == 'jenkins_callback':
                _status = status.HTTP_403_FORBIDDEN
            if not check_branch(commit_tag['name'], allow_branch):
                return Response(data={'code': 50000, 'status': 'failed',
                                      'message': f"{commit_tag['name']}分支不允许{type_map[view_type][1]}！"},
                                status=_status)
            if appinfo_obj.app.category.split('.')[-1] == 'server' and appinfo_obj.app.is_k8s == 'k8s':
                # 后端发布
                if appinfo_obj.kubernetes.count() <= 0:
                    logger.warning(
                        f'应用[{appinfo_obj.uniq_tag}]发版失败, 原因: 该应用未配置Kubernetes集群!')
                    return Response(data={'code': 50000, 'message': '发版失败, 该应用未配置Kubernetes集群!'},
                                    status=_status)
            else:
                # 前端/非k8s部署后端发布
                if not appinfo_obj.hosts:
                    logger.warning(
                        f'应用[{appinfo_obj.uniq_tag}]发版失败, 原因: 该应用未配置部署主机!')
                    return Response(data={'code': 50000, 'message': '发版失败, 该应用未配置部署主机!'},
                                    status=_status)

            return func(self, request, *args, **kwargs)

        return wrapper

    return decorator
