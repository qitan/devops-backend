import os
import time
from datetime import datetime
from functools import wraps
from wsgiref.util import FileWrapper

from django.db import transaction
from django.http import StreamingHttpResponse
from rest_framework.decorators import action
from rest_framework.response import Response
from dbapp.models import MicroApp, Project

from common.exception import OkAPIException
from common.ext_fun import get_datadict, gitlab_cli
from common.extends.authenticate import CookiesAuthentication
from common.extends.handler import log_audit
from common.extends.permissions import RbacPermission
from common.extends.viewsets import CustomModelViewSet
from dbapp.models import UserProfile
from workflow.ext_func import create_workflow
from workflow.lifecycle import LifeCycle
from dbapp.models import Workflow, WorkflowNodeHistory, WorkflowTemplate, WorkflowTemplateRevisionHistory
from workflow.notice import get_member_user_ids
from workflow.serializers import WorkflowListSerializer, WorkflowRetrieveSerializer, WorkflowSerializer, \
    WorkflowNodeHistorySerializer, WorkflowRevisionTemplateSerializer, WorkflowTemplateSerializer, \
    WorkflowNodeHistoryListSerializer
import logging

logger = logging.getLogger('drf')

IS_NOTICE_ASYNC = True


class STATUS:
    close = '已关闭'
    revoke = '已撤回'
    reject = '被驳回'
    wait = '待处理'
    complete = '已完成'


def check_user_is_workflow_member(workflow_obj, user_obj, node=None, check_notice_member=True):

    return True


def check_user_include_workflow_member(members, user_obj, user_departments_obj):

    return True


def check_workflow_permission():
    """
    检查当前用户是否具备访问 or 处理 流程节点的权限
    :param read:
    :return:
    """

    def decorator(func):
        @wraps(func)
        def wrapper(self, request, *args, **kwargs):
            workflow_obj = Workflow.objects.get(wid=kwargs['pk'])
            user = request.user
            method = request.method.lower()
            if method not in ['get', 'put']:
                return Response({
                    'message': f'系统错误， 禁止访问',
                    'code': 40000,
                    'status': 'failed'
                })
            node_name = None
            if method == 'get':
                node_name = request.query_params.get('node', None)
            elif method == 'put':
                node_name = request.data.get('node', None)

            is_admin = RbacPermission.check_is_admin(request)
            # 检查绑定人员 or 部门里是否有当前用户
            if node_name:
                is_workflow_member = check_user_is_workflow_member(workflow_obj, user, node=node_name,
                                                                   check_notice_member=False)

            if method == 'get':
                # 如果用户是超级管理员，或者用户拥有管理员权限，或者工单管理的权限
                permission_methods = RbacPermission.get_permission_from_role(
                    request)
                if 'workflow_all' in permission_methods or is_admin or user.is_superuser:
                    return func(self, request, *args, **kwargs)
                # 如果请求者是工单的发起人
                if user.id == workflow_obj.creator.id:
                    return func(self, request, *args, **kwargs)

                # 检查绑定人员 or 部门里是否有当前用户
                is_workflow_member = check_user_is_workflow_member(
                    workflow_obj, user)
                if is_workflow_member:
                    return func(self, request, *args, **kwargs)

            elif method == 'put':
                if not node_name:
                    return Response({
                        'message': f'请求错误， 节点参数缺失',
                        'code': 40000,
                        'status': 'failed'
                    })

                return func(self, request, *args, **kwargs)
            else:
                return Response({
                    'message': f'工单请求方法错误，不支持',
                    'code': 40000,
                    'status': 'failed'
                })

        return wrapper

    return decorator


class WorkflowViewSetAbstract(CustomModelViewSet):
    queryset = Workflow.objects.all()
    serializer_class = WorkflowSerializer
    filterset_fields = {
        'created_time': ['gte', 'lte'],
        'creator__first_name': ['exact'],
        'status': ['exact'],
    }
    filter_fields = ('template', 'status', 'creator',
                     'node', 'wid', 'created_time')
    search_fields = ('topic', 'wid',)

    def get_serializer_class(self):
        if self.action == 'retrieve':
            return WorkflowRetrieveSerializer
        if self.action == 'list':
            return WorkflowListSerializer
        return WorkflowSerializer


class WorkflowViewSet(WorkflowViewSetAbstract):
    """
    所有工单

    ### 所有工单权限
        {'*': ('admin', '管理员')},
        {'*': ('workflow_all', '工单管理')},
        {'get': ('workflow_list', '查看所有工单')},
        {'get_retrieve': ('workflow_retrieve', '查看指定工单')},
        {'get_node_history': ('workflow_node_history', '查看工单节点操作历史')},
        {'post': ('workflow_create', '发起工单')},
        {'*_template': ('workflow_revision_template_update', '更工单专属模板')},
        {'put_revoke': ('workflow_revoke', '撤回工单')},
        {'put_close': ('workflow_close', '关闭工单')},
        {'get_test': ('workflow_test', '工单接口测试')},
    """
    perms_map = (
        {'*': ('admin', '管理员')},
        {'*': ('workflow_all', '工单管理')},
        {'get': ('workflow_list', '查看所有工单')},
        {'get_retrieve': ('workflow_retrieve', '查看指定工单')},
        {'get_node_history': ('workflow_node_history', '查看工单节点操作历史')},
        {'post': ('workflow_create', '发起工单')},
        {'*_template': ('workflow_revision_template_update', '更工单专属模板')},
        {'put_revoke': ('workflow_revoke', '撤回工单')},
        {'put_close': ('workflow_close', '关闭工单')},
        {'get_test': ('workflow_test', '工单接口测试')},
    )

    @staticmethod
    def members_handle(data, field, leader: UserProfile, owner: UserProfile = None):
        data[field] = list(set(data[field]))
        return data

    @check_workflow_permission()
    def retrieve(self, request, *args, **kwargs):
        instance = self.get_queryset().get(wid=kwargs['pk'])
        serializer = self.get_serializer(instance)
        data = {'data': serializer.data, 'code': 20000, 'status': 'success'}
        return Response(data)

    @transaction.atomic
    def create(self, request, *args, **kwargs):
        workflow_form = request.data['workflow']
        form = request.data['node']
        ok, data = create_workflow(
            form, workflow_form, request.data['template'], request.user)
        if not ok:
            raise OkAPIException({
                'status': 'failed',
                'code': 40000,
                'message': data
            }, code=200)

        life_cycle = LifeCycle(request, data['workflow_obj'],
                               data['node_obj'], form, is_async=IS_NOTICE_ASYNC)
        life_cycle.handle(check_form=False)
        return Response({
            'data': data['data'],
            'status': 'success',
            'code': 20000,
        })

    @transaction.atomic
    def update(self, request, *args, **kwargs):
        return Response({'code': 40000, 'message': '禁止直接编辑工单', 'status': 'failed'})

    @transaction.atomic
    @action(methods=['GET', 'PUT'], url_path='template', detail=True)
    @check_workflow_permission()
    def template(self, request, *args, **kwargs):
        filters = {'wid': kwargs['pk']}
        workflow_obj = self.queryset.get(**filters)
        template_obj = workflow_obj.template

        if request.method.lower() == 'get':
            workflow_template_serializer = WorkflowRevisionTemplateSerializer(
                instance=template_obj)
            return Response({
                'status': 'success',
                'code': 20000,
                'data': workflow_template_serializer.data
            })

        form = request.data['form']
        workflow_template_serializer = WorkflowRevisionTemplateSerializer(
            instance=template_obj, data=form)
        if not workflow_template_serializer.is_valid():
            raise OkAPIException({
                'code': 40000,
                'status': 'failed',
                'message': workflow_template_serializer.errors
            })
        workflow_template_serializer.save()
        data = workflow_template_serializer.data
        data['status'] = 'success'
        data['code'] = 20000
        log_audit(
            request,
            action_type=WorkflowTemplateSerializer.Meta.model.__name__,
            action='更新', content='更新流程模板',
            data=data
        )
        return Response(data)

    @action(methods=['GET'], url_path='node_history', detail=True)
    def node_history(self, request, *args, **kwargs):
        """
        获取流程节点操作历史数据
        :param request:
        :param args:
        :param kwargs:
        :return:
        """
        filters = {'wid': kwargs['pk']}
        workflow_obj = self.queryset.get(**filters)
        instance_list = WorkflowNodeHistory.objects.filter(
            workflow=workflow_obj)
        serializer = WorkflowNodeHistoryListSerializer(
            instance_list, many=True)
        data = {'data': serializer.data, 'code': 20000, 'status': 'success'}
        return Response(data)

    @transaction.atomic
    @action(methods=['PUT'], url_path='revoke', detail=True)
    def revoke(self, request, *args, **kwargs):
        """
        撤回工单
        :param request:
        :param args:
        :param kwargs:
        :return:
        """
        filters = {'pk': kwargs['pk']}
        instance = self.queryset.get(**filters)
        instance.node = instance.template.nodes[0]['name']
        instance.status = instance.STATUS.revoke
        instance.save()
        # 补充一条节点操作记录
        first_node_history = WorkflowNodeHistory.objects.filter(
            workflow=instance,
            node=instance.template.nodes[0]['name'],
        ).first()
        # 复制第一个节点的历史数据， 然后修改保存
        first_node_history.pk = None
        first_node_history.handle_type = WorkflowNodeHistory.HandleType.REVOKE
        first_node_history.operator = request.user
        first_node_history.save()
        return Response({'code': 20000, 'message': '撤回工单成功', 'status': 'success'})

    @transaction.atomic
    @action(methods=['PUT'], url_path='close', detail=True)
    def close(self, request, *args, **kwargs):
        """
        关闭工单
        :param request:
        :param args:
        :param kwargs:
        :return:
        """
        filters = {'pk': kwargs['pk']}
        instance = self.queryset.get(**filters)
        instance.status = instance.STATUS.close
        instance.save()
        # 补充一条节点操作记录
        first_node_history = WorkflowNodeHistory.objects.filter(
            workflow=instance,
            node=instance.template.nodes[0]['name'],
        ).first()
        # 复制第一个节点的历史数据， 然后修改保存
        first_node_history.pk = None
        first_node_history.handle_type = WorkflowNodeHistory.HandleType.CLOSE
        first_node_history.operator = request.user
        first_node_history.save()
        return Response({'code': 20000, 'message': '关闭工单成功', 'status': 'success'})

    @transaction.atomic
    @action(methods=['PUT'], url_path='complete', detail=True)
    def complete(self, request, *args, **kwargs):
        """
        工单结单
        :param request:
        :param args:
        :param kwargs:
        :return:
        """
        filters = {'pk': kwargs['pk']}
        instance = self.queryset.get(**filters)
        instance.status = instance.STATUS.complete
        instance.save()
        # 补充一条节点操作记录
        first_node_history = WorkflowNodeHistory.objects.filter(
            workflow=instance,
            node=instance.template.nodes[0]['name'],
        ).first()
        # 复制第一个节点的历史数据， 然后修改保存
        first_node_history.pk = None
        first_node_history.handle_type = WorkflowNodeHistory.HandleType.CLOSE
        first_node_history.operator = request.user
        first_node_history.save()
        return Response({'code': 20000, 'message': '工单结单成功', 'status': 'success'})
