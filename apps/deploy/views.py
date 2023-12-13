#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
@Author : Charles Lai
@Contact : qqing_lai@hotmail.com
@Time : 2020/9/29 下午3:07
@FileName: views.py
@Blog ：https://imaojia.com
"""
import base64
from collections import OrderedDict
from functools import reduce
import operator

from django_q.tasks import async_task
from django.core.cache import cache
from django.db.models import Q
from rest_framework import status, exceptions
from rest_framework.decorators import action, permission_classes
from rest_framework.response import Response

from rest_framework.filters import OrderingFilter
import django_filters
from django.db import transaction
from celery_tasks.celery import app as celery_app
from deploy.rds_transfer import rds_transfer_es
from qtasks.tasks_build import JenkinsBuild, build_number_binding
from dbapp.model.model_cmdb import DevLanguage
from dbapp.models import MicroApp, AppInfo, KubernetesDeploy, Idc
from common.custom_format import convert_xml_to_str_with_pipeline
from common.extends.decorators import branch_allow_check, build_allow_check, deploy_allow_check
from deploy.documents_order import PublishAppDocument
from deploy.ext_func import app_build_handle, app_deploy_handle, check_user_deploy_perm, deploy_handle
from dbapp.model.model_deploy import BuildJob, PublishApp, PublishOrder, DockerImage, DeployJob, \
    BuildJobResult, DeployJobResult
from dbapp.model.model_ucenter import SystemConfig, UserProfile, DataDict
from deploy.serializers import BuildJobListSerializer, DeployJobListForRollbackSerializer, DockerImageSerializer, DeployJobSerializer, \
    DeployJobListSerializer, BuildJobResultSerializer, DeployJobResultSerializer
from deploy.serializers_order import PublishAppSerializer, PublishOrderSerializer, PublishOrderListSerializer, \
    PublishOrderDetailSerializer

from common.variables import *
from common.extends.permissions import AppDeployPermission
from common.extends.viewsets import CustomModelViewSet
from common.extends.filters import CustomSearchFilter
from common.extends.handler import log_audit
from common.utils.JenkinsAPI import GlueJenkins
from common.utils.AesCipher import AesCipher
from common.utils.HarborAPI import HarborAPI
from common.ext_fun import get_datadict, get_deploy_image_list, get_redis_data, gitlab_cli, harbor_cli, \
    k8s_cli, template_generate, \
    time_comp, get_time_range
from jenkins import NotFoundException as JenkinsNotFoundException

from deploy.documents import DeployJobDocument, BuildJobDocument, BuildJobResultDocument, DeployJobResultDocument

from config import MEDIA_ROOT, PROD_TAG, BASE_DIR, PLAYBOOK_PATH

from ruamel import yaml
import django_excel as excel
import os
import datetime
import json
import xmltodict
import zipfile

import logging

logger = logging.getLogger('drf')


class PublishAppViewSet(CustomModelViewSet):
    """
    发布单待发布应用视图

    ### 权限
        {'*': ('publish_all', '发布工单管理')},
        {'get': ('publish_list', '查看发布工单')},
        {'post': ('publish_create', '创建发布工单')},
        {'put': ('publish_edit', '编辑发布工单')},
        {'patch': ('publish_edit', '编辑发布工单')},
        {'delete': ('publish_delete', '删除发布工单')}
    """
    perms_map = (
        {'*': ('admin', '管理员')},
        {'*': ('publish_all', '发布工单管理')},
        {'get': ('publish_list', '查看发布工单')},
        {'post': ('publish_create', '创建发布工单')},
        {'put': ('publish_edit', '编辑发布工单')},
        {'patch': ('publish_edit', '编辑发布工单')},
        {'delete': ('publish_delete', '删除发布工单')}
    )
    queryset = PublishApp.objects.all()
    serializer_class = PublishAppSerializer
    document = PublishAppDocument
    custom_action = []

    @transaction.atomic
    def partial_update(self, request, *args, **kwargs):
        response = super(PublishAppViewSet, self).partial_update(
            request, *args, **kwargs)
        status = request.data.get('status')
        if status == 4:
            pk = kwargs['pk']
            pub_app = PublishApp.objects.get(id=pk)
            pub_order = PublishOrder.objects.get(order_id=pub_app.order_id)
            order_apps = pub_order.apps.all()
            # 如果所有app都是 status 4 ， 作废状态， 则工单状态也设置为 4
            if order_apps.count() == pub_order.apps.filter(status=4).count():
                pub_order.status = 4
                pub_order.save()
            elif not order_apps.filter(Q(status=0) | Q(status=2) | Q(status=3)).exclude(id=pub_app.id):
                # 如果除去当前app, 剩下的APP中已经不存在 未发布 和 发布失败的 、发布中的 ， 则 工单改为完成
                pub_order.status = 1
                pub_order.save()
        return response

    def get_serializer_class(self):
        return PublishAppSerializer


class PublishOrderViewSet(CustomModelViewSet):
    """
    发布工单视图

    ### 发布工单权限
        {'*': ('publish_all', '发布工单管理')},
        {'get': ('publish_list', '查看发布工单')},
        {'post': ('publish_create', '创建发布工单')},
        {'put': ('publish_edit', '编辑发布工单')},
        {'patch': ('publish_edit', '编辑发布工单')},
        {'delete': ('publish_delete', '删除发布工单')}
    """
    perms_map = (
        {'*': ('admin', '管理员')},
        {'*': ('publish_all', '发布工单管理')},
        {'get': ('publish_list', '查看发布工单')},
        {'post': ('publish_create', '创建发布工单')},
        {'put': ('publish_edit', '编辑发布工单')},
        {'patch': ('publish_edit', '编辑发布工单')},
        {'delete': ('publish_delete', '删除发布工单')}
    )
    queryset = PublishOrder.objects.all()
    serializer_class = PublishOrderSerializer
    serializer_list_class = PublishOrderListSerializer
    serializer_upcoming_class = PublishOrderListSerializer
    serializer_retrieve_class = PublishOrderDetailSerializer
    filter_backends = (django_filters.rest_framework.DjangoFilterBackend,
                       CustomSearchFilter)
    filter_fields = {
        'environment': ['exact'],
        'created_time': ['gte', 'lte'],
        'creator__first_name': ['exact', 'icontains'],
        'status': ['in', 'exact'],
    }
    search_fields = ('order_id', 'dingtalk_tid', 'title',
                     'content', 'effect', 'creator__first_name')
    ordering_fields = ['update_time', 'created_time', 'status', 'category']
    ordering = ['-id', '-update_time']

    def extend_filter(self, queryset):
        if self.action == 'upcoming':
            queryset = queryset.filter(status__in=[0, 2, 3, 11, 12, 13])
        if not (self.request.user.is_superuser or 'admin' in self.get_permission_from_role(
                self.request)):
            user_id = self.request.user.id
            queryset = queryset.filter(Q(team_members__contains=user_id) | Q(
                extra_deploy_members__contains=user_id))

        # 待发版 和 发版中 状态的工单挨个判断是否超时， 超时的直接状态改成废弃
        publish_time_expire_conf = json.loads(
            DataDict.objects.get(key='PUBLISH_TIME_DIFF').extra)
        for item in queryset:
            if item.status in [0, 3] and time_comp(item.expect_time, **publish_time_expire_conf) is False:
                logger.info(
                    f'工单 {item} 超时，状态修改为废弃。 计划发版时间： {item.expect_time} 超时配置：{publish_time_expire_conf}')
                item.status = 4
                item.save()
        return queryset

    def perform_create(self, serializer):
        apps = self.request.data['app']
        try:
            # 去重
            apps = reduce(lambda x, y: x if y in x else x + [y], [[], ] + apps)
        except:
            pass
        # 当前环境id
        environment = self.request.data['environment']
        serializer.save(creator=self.request.user)

        # 同步镜像任务
        async_task('qtasks.tasks.docker_image_sync', *[],
                   **{'apps': apps, 'env': environment})
        data = serializer.data
        # 工单通知运维
        payload = {
            'creator': self.request.user.first_name or self.request.user.username,
            'apps': apps,
            'title': data['title'],
            'order_id': data['order_id'],
            'id': data['id'],
            'created_time': data['created_time'],
            'expect_time': data['expect_time']
        }
        async_task('qtasks.tasks.publishorder_notify', *[], **payload)

    @action(methods=['GET'], url_path='count', detail=False)
    def count(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset()).filter(
            status__in=[0, 2, 3, 11, 12, 13])
        return Response({'code': 20000, 'data': queryset.count()})

    @action(methods=['GET'], url_path='upcoming', detail=False)
    def upcoming(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)


class DeployJobViewSet(CustomModelViewSet):
    """
    持续部署视图

    ### 持续部署权限
        {'*': ('cicd_all', 'CICD管理')},
        {'get': ('cicd_list', '查看CICD')},
        {'post': ('cicd_create', '创建CICD')},
        {'put': ('cicd_edit', '编辑CICD')},
        {'patch': ('cicd_edit', '编辑CICD')},
        {'delete': ('cicd_delete', '删除CICD')}

    ### 部署结果

    """
    perms_map = (
        {'*': ('admin', '管理员')},
        {'*': ('cicd_all', 'CICD管理')},
        {'get': ('cicd_list', '查看CICD')},
        {'post': ('cicd_create', '创建CICD')},
        {'put': ('cicd_edit', '编辑CICD')},
        {'patch': ('cicd_edit', '编辑CICD')},
        {'delete': ('cicd_delete', '删除CICD')}
    )
    document = DeployJobDocument
    document_result = DeployJobResultDocument
    queryset = DeployJob.objects.all()
    queryset_result = DeployJobResult.objects.all()
    serializer_class = DeployJobSerializer
    serializer_result_class = DeployJobResultSerializer
    filter_backends = (django_filters.rest_framework.DjangoFilterBackend,
                       CustomSearchFilter)
    filter_fields = ('appinfo_id', 'deployer', 'status', 'order_id', 'modules')
    search_fields = ('uniq_id', 'image')
    ordering_fields = ['update_time', 'created_time', 'status', 'deploy_type']
    ordering = ['-update_time']
    custom_action = ['list', 'retrieve', 'deploy_history', 'deploy_result', 'cicd_dashboard_app_rollback',
                     'rollback_app_download']

    def extend_filter(self, queryset):
        if self.action == 'deploy_history':
            queryset = queryset.filter(order_id__isnull=False)
        return queryset

    def get_serializer_class(self):
        if self.action in self.custom_action:
            return DeployJobListSerializer
        if self.action == 'list_rollback_image':
            return DeployJobListForRollbackSerializer
        return DeployJobSerializer

    @branch_allow_check('cd')
    @deploy_allow_check('cd')
    def create(self, request, *args, **kwargs):
        # 前端/非k8s部署后端要发布的目标主机
        target_hosts = request.data.get('hosts', [])
        modules = request.data.get('modules', None)
        logger.info(f'目标主机========= {target_hosts}')
        # 部署新应用
        deploy_apply = request.data.get('apply', None)
        # 版本回退标识
        rollback = request.data.get('rollback', False)
        # force = request.data.get('force', False)
        force = True  # 一律更改为强制更新, 即使用replace方法更新deployment
        appinfo_obj = AppInfo.objects.get(id=request.data['appinfo_id'])

        user_obj = self.request.user
        # 使用工单发版的情况下, 检验当前用户是否有当前环境区域发布权限
        if all([not check_user_deploy_perm(user_obj, appinfo_obj, **{'perms': self.get_permission_from_role(request), 'pub_order': None}),
                appinfo_obj.environment.ticket_on, [appinfo_obj.app.project.product.region.name,
                                                    appinfo_obj.app.project.product.name] not in appinfo_obj.environment.extra.get(
                'product', [])]):
            # 启用工单必须走发版申请
            logger.info(
                f'应用[{appinfo_obj.uniq_tag}]发版被拒绝, 原因: 该应用不允许直接发布,请提交发版申请!')
            return Response({'code': 40300, 'message': '该应用不允许直接发布,请提交发版申请!'})

        if rollback:
            # 标记版本回滚
            request.data['deploy_type'] = 2
        request.data['appid'] = appinfo_obj.app.appid

        if modules:
            request.data['modules'] = modules.split(':')[-1]
        try:
            ok, data = app_deploy_handle(
                request.data, appinfo_obj, self.request.user)
            if ok:
                return Response({'data': data, 'status': 'success', 'code': 20000})
            return Response({'message': data, 'code': 50000})
        except BaseException as e:
            logger.exception(
                f"工单应用[{appinfo_obj.uniq_tag}]发版失败, 原因: 出现异常, {str(e)}！")
            return Response({'code': 50000, 'status': 'failed', 'message': str(e)})

    def perform_create(self, serializer):
        uniq_id = f'{self.request.data["appinfo_id"]}-{datetime.datetime.now().strftime("%Y%m%d%H%M%S")}'
        if self.request.data.get('modules', None):
            uniq_id += f'-{self.request.data["modules"]}'
        serializer.save(deployer=self.request.user, uniq_id=uniq_id)

    @branch_allow_check('jenkins_callback')
    @transaction.atomic
    @action(methods=['POST'], url_path='callback', detail=False,
            perms_map=({'post': ('jenkins_callback', 'Jenkins回调')},))
    def deploy_callback(self, request):
        """
        Jenkins回调

        ### Jenkins任务结束后回调，继续发布应用
        """
        build_job = BuildJob.objects.get(id=request.data.get('jobid'))
        try:
            appinfo_obj = AppInfo.objects.get(id=build_job.appinfo_id)
        except BaseException as e:
            logger.exception(f"获取应用[ID: {build_job.appinfo_id}]异常, 原因: {e}")
            return Response(data={'code': 50000, 'message': f'发版失败, 原因: 获取应用异常, {e}!'},
                            status=status.HTTP_404_NOT_FOUND)

        data = {
            'appid': build_job.appid,
            'appinfo_id': build_job.appinfo_id,
            'image': build_job.image,
            'kubernetes': [i.id for i in appinfo_obj.kubernetes.all()],
            'modules': build_job.modules,
            'batch_uuid': build_job.batch_uuid
        }
        init_point = transaction.savepoint()
        serializer = self.get_serializer(data=data)

        if not serializer.is_valid():
            logger.info(
                f'Jenkins回调发布应用[{appinfo_obj.uniq_tag}失败, 原因: {serializer.errors}')
            return Response(data={'code': 40000, 'status': 'failed', 'message': serializer.errors},
                            status=status.HTTP_400_BAD_REQUEST)
        try:
            serializer.save(uniq_id=f'{build_job.appinfo_id}-{datetime.datetime.now().strftime("%Y%m%d%H%M%S")}',
                            deployer=build_job.deployer)
            image = build_job.image
            ret = deploy_handle(serializer.data.get('id'), serializer.data[
                'kubernetes'] if appinfo_obj.app.is_k8s == 'k8s' else appinfo_obj.hosts, appinfo_obj, image, force=True)
            if ret['code'] == 500:
                # k8s deployment模板生成失败, 不创建上线申请记录
                transaction.savepoint_rollback(init_point)
                logger.exception(
                    f"Jenkins回调发布应用[{appinfo_obj.uniq_tag}失败, 原因: 模板生成失败, {ret['message']}")
                return Response(data={'code': 50000, 'message': ret['message']},
                                status=status.HTTP_424_FAILED_DEPENDENCY)
        except BaseException as e:
            logger.exception(
                f'Jenkins回调发布应用[{appinfo_obj.uniq_tag}失败, 原因: 出现异常, {str(e)}')
            return Response(data={'code': 50000, 'status': 'failed', 'message': str(e)},
                            status=status.HTTP_424_FAILED_DEPENDENCY)
        log_audit(request, action_type=self.serializer_class.Meta.model.__name__, action='创建', content='',
                  data=serializer.data)

        data = {'data': serializer.data, 'status': 'success', 'code': 20000}
        return Response(data)

    @action(methods=['POST'], url_path='result', detail=True, perms_map=({'post': ('cicd_list', '查看CICD')},))
    def deploy_result(self, request, pk=None):
        """
        获取发布结果

        ### 传递参数
            无
        """
        job = self.queryset.get(id=self.kwargs['pk'])
        job_result = self.queryset_result.filter(job_id=pk)
        if job_result.count():
            job_result = job_result.first()
            if job.status != 3 and job_result.result:
                job_result_serializer = self.serializer_result_class(
                    job_result)
                return Response({'code': 20000, 'data': job_result_serializer.data})
        logger.debug(f'job status === {job.status}')
        if job.status == 3:
            return Response({'code': 20400, 'data': None})

        return Response({'code': 20400, 'data': '后台查询中, 请稍候查看!'})

    @action(methods=['GET'], url_path='history', detail=False)
    def deploy_history(self, request, pk=None):
        """
        工单发布历史
        """
        return super().list(request)

    @transaction.atomic
    @action(methods=['POST'], url_path='reset_status', detail=True)
    def reset_status(self, request, pk=None):
        pub_app_id = request.data.get('publishAppId', '')
        if pub_app_id:
            # 如果是工单发版的情况下， 获取最新的DeployJob
            obj = PublishApp.objects.get(id=pub_app_id)
            if obj.status != 3:
                return Response({
                    'code': 40000,
                    'status': 'failed',
                    'message': f'当前状态不允许重置: {obj.status}'
                })
            obj.status = 0
            obj.save()
            filters = {'order_id': obj.order_id,
                       'appinfo_id': obj.appinfo_id, 'status': 3}
        else:
            obj = self.queryset.get(id=pk)
            filters = {'appinfo_id': obj.appinfo_id, 'status': 3}
            if obj.batch_uuid:
                # 获取同一批次发布的任务
                filters['batch_uuid'] = obj.batch_uuid
        objs = self.queryset.filter(**filters)
        objs.update(status=0)

        return Response({
            'code': 20000,
            'status': 'success',
            'message': '重置状态成功'
        })

    @action(methods=['GET'], url_path='rollback/image', detail=False)
    def list_rollback_image(self, request):
        """
        应用回退镜像列表

        ### 请求参数：
            appinfo_id: 应用模块ID
            modules: 前端模块
        """
        appinfo_id = request.query_params.get('appinfo_id', None)
        # 前端发布模块
        modules = request.query_params.get('modules', 'dist')
        appinfo_obj = AppInfo.objects.get(id=appinfo_id)
        queryset = self.queryset.filter(appinfo_id=appinfo_obj.id, status=1)
        current_version_prev = queryset.filter(
            image__contains=appinfo_obj.version).last()
        rollback_image_objs = DeployJob.objects.raw(f"""
                        SELECT
                            *
                        FROM
                            (
                            SELECT
                                ANY_VALUE ( id ) AS id,
                                image 
                            FROM
                                `deploy_deployjob` 
                            WHERE
                                ( `deploy_deployjob`.id < {current_version_prev.id} AND `deploy_deployjob`.`appinfo_id` = {appinfo_obj.id} AND `deploy_deployjob`.`status` = 1 ) 
                            GROUP BY
                                image 
                            ) AS a 
                        ORDER BY
                            a.id DESC
                        LIMIT 50
                    """)
        image_list = {i.image: i.id for i in rollback_image_objs}
        queryset = queryset.filter(id__in=image_list.values())
        if not queryset:
            return Response({'code': 20000, 'data': []})
        queryset = DeployJob.objects.raw(f"""
                SELECT * FROM `deploy_deployjob` dj
                                         LEFT JOIN `deploy_buildjob` bj
                                          ON dj.image = bj.image
                                         WHERE dj.id in {tuple(image_list.values())}
                                        ORDER BY dj.id DESC
                                        LIMIT 50
                                         """)
        serializer = self.get_serializer(queryset[:20], many=True)
        return Response({'code': 20000, 'data': serializer.data})


class BuildJobViewSet(CustomModelViewSet):
    """
    构建发布视图

    ### 构建发布权限
        {'*': ('cicd_all', 'CICD管理')},
        {'get': ('cicd_list', '查看CICD')},
        {'post': ('cicd_create', '创建CICD')},
        {'put': ('cicd_edit', '编辑CICD')},
        {'patch': ('cicd_edit', '编辑CICD')},
        {'delete': ('cicd_delete', '删除CICD')}

    ### 构建结果
        status: {'SUCCESS': 1, 'FAILED': 2, 'ABORTED': 4, 'FAILURE': 2, 'IN_PROGRESS': 3, 'NOT_EXECUTED': 5}
    """
    perms_map = (
        {'*': ('admin', '管理员')},
        {'*': ('cicd_all', 'CICD管理')},
        {'get': ('cicd_list', '查看CICD')},
        {'post': ('cicd_create', '创建CICD')},
        {'put': ('cicd_edit', '编辑CICD')},
        {'patch': ('cicd_edit', '编辑CICD')},
        {'delete': ('cicd_delete', '删除CICD')}
    )
    document = BuildJobDocument
    document_result = BuildJobResultDocument
    queryset = BuildJob.objects.all()
    queryset_result = BuildJobResult.objects.all()
    serializer_class = BuildJobListSerializer
    serializer_result_class = BuildJobResultSerializer
    filter_backends = (django_filters.rest_framework.DjangoFilterBackend,
                       CustomSearchFilter, OrderingFilter)
    filter_fields = ('appinfo_id', 'order_id', 'is_deploy', 'status',)
    search_fields = ('appinfo_id', 'is_deploy', 'status',)
    ordering_fields = ['update_time', 'created_time', 'status', 'is_deploy']
    ordering = ['-update_time']
    custom_action = []

    @action(methods=['GET'], url_path='sync', detail=False)
    def list_build_image(self, request):
        """
        获取允许同步的构建镜像列表

        ### 请求参数
            app_id: MicroApp ID
        """
        # 废弃
        app_id = request.query_params.get('app_id')
        queryset = self.get_deploy_image_list(app_id)
        serializer = self.get_serializer(queryset, many=True)
        return Response({'code': 20000, 'data': serializer.data})

    @action(methods=['GET'], url_path='app/image', detail=False)
    def list_deploy_image(self, request):
        """
        发版申请页面镜像列表

        ### 请求参数
            app_id: MicroApp ID
        """
        app_id = request.query_params.get('app_id')
        appinfo_id = request.query_params.get('appinfo_id')
        module = request.query_params.get('module', None)
        force = request.query_params.get('force', 0)

        queryset = get_deploy_image_list(app_id, appinfo_id, module)
        if queryset is None:
            return Response({'code': 20000, 'data': []})

        data = [{'id': i.id, 'appinfo_id': i.appinfo_id, 'commits': i.commits, 'commit_tag': i.commit_tag,
                 'status': i.status,
                 'image': i.image} for i in queryset]
        return Response({'code': 20000, 'data': data})

    @action(methods=['GET'], url_path='cd/image', detail=False)
    def list_cd_image(self, request):
        """
        持续部署页面镜像列表

        ### 请求参数
            appinfo_id: 应用模块ID
        """
        appinfo_id = request.query_params.get('appinfo_id')
        # 前端发布模块
        modules = request.query_params.get('modules', 'dist')
        # 获取关联应用ID
        appinfo_obj = AppInfo.objects.get(id=appinfo_id)

        if appinfo_obj.app.multiple_app:
            appinfo_objs = AppInfo.objects.filter(app_id__in=appinfo_obj.app.multiple_ids,
                                                  environment=appinfo_obj.environment)
            queryset = self.queryset.filter(appinfo_id__in=list(
                set([i.id for i in appinfo_objs])), status=1)
        else:
            queryset = self.queryset.filter(
                appinfo_id=appinfo_obj.id, status=1)
        serializer = self.get_serializer(queryset[:10], many=True)
        return Response({'code': 20000, 'data': serializer.data})

    @action(methods=['GET'], url_path='tag', detail=True)
    def image_tags(self, request, pk=None):
        """
        镜像标签

        ### 获取镜像标签
        :param pk: AppInfo ID
        """
        queryset = self.queryset.filter(appinfo_id=pk, status=1)
        data = {
            'data': {'total': queryset.count(), 'items': [{'name': i.mirror_tag} for i in queryset if i.mirror_tag]},
            'code': 20000, 'status': 'success'}
        return Response(data)

    @action(methods=['POST'], url_path='callback', detail=False,
            perms_map=({'post': ('jenkins_callback', 'Jenkins回调')},))
    def build_callback(self, request):
        """
        Jenkins回调

        ### Jenkins任务结束后回调，平台获取结果入库
        :param appinfo_id: AppInfo ID
        """
        job_id = request.data.get('job_id', None)
        if not job_id:
            return Response({'code': 50000, 'message': '未获取到任务ID.'})
        appinfo_id = request.data.get('appinfo_id', None)

        if job_id and appinfo_id:
            async_task('qtasks.tasks_build.jenkins_callback_handle', *[], **
                       {'job_id': int(job_id), 'appinfo_id': int(appinfo_id), 'job_type': 'app'})
            return Response({'code': 20000, 'data': '平台已收到通知'})
        return Response({'code': 50000, 'message': '获取不到参数.'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(methods=['POST'], url_path='result', detail=True, perms_map=({'post': ('cicd_list', '查看CICD')},))
    def build_result(self, request, pk=None):
        """
        获取构建结果

        ### 获取Jenkins构建结果
        """
        job = self.queryset.get(id=self.kwargs['pk'])
        job_result = self.queryset_result.filter(job_id=pk)
        if job_result.count():
            job_result = job_result.first()
            if job.status != 3 and job_result.console_output:
                job_result_serializer = self.serializer_result_class(
                    job_result)
                return Response({'code': 20000, 'data': job_result_serializer.data})
        async_task('qtasks.tasks_build.jenkins_callback_handle', *[], **
                   {'job_id': job.id, 'appinfo_id': job.appinfo_id, 'job_type': 'app'})
        return Response({'code': 20000, 'data': '正在查询结果, 请稍候再查看!'})

    @action(methods=['POST'], url_path='deploy/stop', detail=True,
            perms_map=({'post': ('stop_continue_build', '中止构建')},))
    def stop_job(self, request, pk=None):
        """
        中止构建
        """
        appinfo_id = pk
        job_id = request.data.get('job_id')
        try:
            appinfo_obj = AppInfo.objects.get(id=appinfo_id)
        except AppInfo.DoesNotExist:
            logger.error(f'获取应用[ID: {appinfo_id}]失败, 原因: 应用环境未配置')
            return Response({'code': 40000, 'status': 'failed', 'message': '应用环境未配置！'})
        jenkins = get_redis_data('cicd-jenkins')
        jenkins_cli = GlueJenkins(jenkins.get('url', 'http://localhost'), username=jenkins.get('user', 'admin'),
                                  password=jenkins.get('password', None))
        stop_build = request.data.get('stop_build', None)
        job_name = appinfo_obj.jenkins_jobname
        if stop_build == '1':
            try:
                job = self.queryset.get(id=job_id)
                jobs = [job]
                if job.batch_uuid:
                    jobs = self.queryset.filter(
                        appinfo_id=job.appinfo_id, batch_uuid=job.batch_uuid)
                for job in jobs:
                    # 中止jenkins构建任务
                    if job.status != 3:
                        logger.info(f'任务{job}状态非构建中，跳过中止操作.')
                        continue
                    try:
                        jenkins_cli.stop_build(job_name, job.build_number)
                    except JenkinsNotFoundException as e:
                        pass
                    finally:
                        pass
                    job.status = 4
                    job.save()
                    if cache.get(f'{JENKINS_CALLBACK_KEY}{job.id}') is None:
                        try:
                            async_task('qtasks.tasks_build.jenkins_callback_handle', *[], **
                                       {'job_id': job.id, 'appinfo_id': appinfo_id, 'job_type': 'app'})
                        except BaseException as e:
                            pass
                return Response({'code': 20000, 'status': 4, 'data': '应用构建任务已中止...'})
            except BuildJob.DoesNotExist:
                return Response({'code': 20000, 'status': 4, 'data': '应用构建任务已经中止...'})
        return Response({'code': 50000, 'status': 'failed', 'data': '非法请求!'})

    @action(methods=['POST'], url_path='build', detail=True, perms_map=({'post': ('continue_build', '持续构建')},))
    @permission_classes((AppDeployPermission,))
    @branch_allow_check('ci')
    @build_allow_check()
    @transaction.atomic
    def build_job(self, request, pk=None):
        """
        持续构建

        ### 持续构建权限
            {'post': ('continue_build', '持续构建')}
        """
        appinfo_obj = AppInfo.objects.get(pk=pk)
        ok, data = app_build_handle(
            request.data, appinfo_obj, request.user)
        if ok:
            return Response({'code': 20000, 'data': data})
        return Response({'code': 50000, 'message': data})
