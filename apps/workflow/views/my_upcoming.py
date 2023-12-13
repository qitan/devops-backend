from django.db import transaction
from rest_framework.decorators import action
from rest_framework.response import Response
from workflow.views.workflow import WorkflowViewSetAbstract, check_workflow_permission, \
    check_user_include_workflow_member, IS_NOTICE_ASYNC

from common.exception import OkAPIException
from common.extends.handler import log_audit
from dbapp.models import UserProfile
from ucenter.serializers import UserProfileListSerializers
from workflow.lifecycle import LifeCycle
from dbapp.models import WorkflowNodeHistory, Workflow
from workflow.notice import get_member_user_ids
from workflow.serializers import WorkflowNodeHistorySerializer

import logging

logger = logging.getLogger(__name__)


class WorkflowMyUpComingViewSet(WorkflowViewSetAbstract):
    """
    我的待办

    ### 我的待办 权限
        {'*': ('admin', '管理员')},
        {'*': ('workflow_all', '工单管理')},
        {'get': ('workflow_my_upcoming_list', '查看我的待办工单')},
        {'put': ('workflow_handle', '处理工单')},
    """
    perms_map = (
        {'*': ('admin', '管理员')},
        {'*': ('workflow_all', '工单管理')},
        {'get': ('workflow_my_upcoming_list', '查看我的待办工单')},
        {'put': ('workflow_handle', '处理工单')},
    )

    @transaction.atomic
    @check_workflow_permission()
    def update(self, request, *args, **kwargs):
        """
        处理流程
        :param request:
        :param args:
        :param kwargs:
        :return:
        """
        filters = {'wid': kwargs['pk']}
        workflow_obj = self.queryset.get(**filters)
        current_node = request.data['node']
        form = request.data['form']
        passed = WorkflowNodeHistory.HandleType.PASSED
        handle_type = form.get('handle_type', passed)
        if not handle_type:
            if workflow_obj.template.node_list.index(workflow_obj.node) == 0:
                handle_type = passed
                form['handle_type'] = passed
            else:
                return Response({
                    'message': '缺少参数 审批类型', 'code': 40000, 'status': 'failed'
                })
        node_form = {
            'workflow': workflow_obj.pk,
            'node': workflow_obj.node,
            'form': form,
            'handle_type': handle_type == passed and passed or WorkflowNodeHistory.HandleType.REJECT,
            'operator': request.user.id
        }
        # 将新的节点数据插入到数据库
        node_serializer = WorkflowNodeHistorySerializer(data=node_form)
        if not node_serializer.is_valid():
            raise OkAPIException({
                'code': 40000,
                'status': 'failed',
                'message': node_serializer.errors
            })
        node_obj = node_serializer.save()
        logger.debug(f'node_obj.handle_type === {node_obj.handle_type}')
        workflow_obj.status = workflow_obj.STATUS.wait
        # 判断是否指定了下一个节点处理人
        # 如果指定了， 直接修改当前工单绑定的模板节点数据
        next_handle_user_list = form.get('next_handle_user')
        if handle_type == passed and next_handle_user_list:
            template_obj = workflow_obj.template
            next_node_conf = template_obj.nodes[template_obj.node_list.index(
                workflow_obj.node) + 1]
            member_list = []
            for user_id in next_handle_user_list:
                user_obj = UserProfile.objects.filter(id=user_id)
                if not user_obj:
                    continue
                user_obj = user_obj.first()
                member_list.append(f'user@{user_obj.id}@{user_obj}')
            next_node_conf['members'] = member_list
            template_obj.save()

        workflow_obj.save()
        life_cycle = LifeCycle(request, workflow_obj,
                               node_obj, form, is_async=IS_NOTICE_ASYNC)
        life_cycle.handle()
        data = node_serializer.data
        data['status'] = 'success'
        data['code'] = 20000
        log_audit(
            request,
            action_type=self.serializer_class.Meta.model.__name__,
            action='创建', content='',
            data=data
        )
        return Response(data)

    @transaction.atomic
    @action(methods=['GET'], url_path='next_handle_users', detail=True)
    def next_handle_users(self, request, *args, **kwargs):
        filters = {'wid': kwargs['pk']}
        workflow_obj = self.queryset.get(**filters)
        template_obj = workflow_obj.template
        cur_node = request.GET['node']
        next_node_index = template_obj.node_list.index(cur_node) + 1
        if next_node_index >= len(template_obj.nodes):
            return Response({
                'code': 40000,
                'status': 'failed',
                'message': '当前节点已经是最后一个节点'
            })

        next_node_conf = template_obj.nodes[next_node_index]
        node_members = next_node_conf.get('members', [])
        member_ids = get_member_user_ids(node_members)
        member_objs = UserProfile.objects.filter(
            id__in=member_ids
        )
        serializer = UserProfileListSerializers(member_objs, many=True)
        return Response({
            'total': member_objs.count(),
            'items': serializer.data,
            'code': 20000,
            'status': 'success'
        })

    def extend_filter(self, queryset):
        queryset = queryset.exclude(
            status__in=[Workflow.STATUS.complete, Workflow.STATUS.close])
        queryset_list = self._get_current_node_members_include_me_workflow(
            queryset)
        ignore_id_list = []
        for wf in queryset_list:
            if wf.cur_node_conf.get('pass_type', '') == 'countersigned':
                user_node_his_objs = WorkflowNodeHistory.objects.filter(
                    operator=self.request.user,
                    node=wf.node,
                    handle_type=WorkflowNodeHistory.HandleType.PASSED
                )
                if user_node_his_objs.count() > 0:
                    ignore_id_list.append(wf.id)
        return queryset_list.exclude(id__in=ignore_id_list)

    def _get_current_node_members_include_me_workflow(self, queryset):
        match_id_list = []
        user_obj = self.request.user
        user_departments_obj = UserProfile.objects.get(
            id=user_obj.id).department.all()
        for i in queryset:
            data_id = i.id
            node_name = i.node
            node_conf = i.cur_node_conf
            if not node_conf:
                continue
            members = node_conf.get('members', [])
            # 如果是驳回状态的流程
            # 判断发起人跟当前用户是否匹配
            if i.status == Workflow.STATUS.reject:
                if i.creator == user_obj:
                    match_id_list.append(data_id)
                continue
            if len(members) > 0 and check_user_include_workflow_member(members, user_obj, user_departments_obj):
                match_id_list.append(data_id)
        return queryset.filter(id__in=match_id_list)

    @action(methods=['GET'], url_path='count', detail=False)
    def count(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        return Response({'code': 20000, 'data': queryset.count()})
