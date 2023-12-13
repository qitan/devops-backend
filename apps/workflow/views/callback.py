from django.db import transaction
from rest_framework.decorators import action
from rest_framework.response import Response
from django.utils import timezone
from django_q.tasks import async_task
from common.extends.viewsets import CustomModelViewSet
from workflow.callback_common import callback_work
from dbapp.models import WorkflowNodeHistoryCallback
from workflow.serializers import WorkflowNodeHistoryCallbackSerializer
import logging

logger = logging.getLogger(__name__)


class WorkflowNodeHistoryCallbackViewSet(CustomModelViewSet):
    """
    工单历史回调信息

    ### 工单历史回调信息
    perms_map = (
        {'*': ('admin', '管理员')},
        {'*': ('workflow_callback_all', '工单回调管理')},
        {'get': ('workflow_callback_get', '获取工单回调')},
        {'post': ('workflow_callback_exec', '执行工单回调')},
    )
    """
    perms_map = (
        {'*': ('admin', '管理员')},
        {'*': ('workflow_callback', '工单回调管理')},
        {'get': ('workflow_callback_get', '获取工单回调')},
        {'post': ('workflow_callback_exec', '执行工单回调')},
        {'post_retry': ('workflow_callback_retry', '重新执行工单回调')},
    )
    queryset = WorkflowNodeHistoryCallback.objects.all()
    serializer_class = WorkflowNodeHistoryCallbackSerializer

    @transaction.atomic
    def create(self, request, *args, **kwargs):
        """
        """
        data = request.data
        action = data.get('action', 'normal')
        callback_type = data['callbackType']
        callback_conf = data['callbackConf']
        callback_url = callback_conf['url']
        init_point = transaction.savepoint()
        cb_obj = WorkflowNodeHistoryCallback.objects.create(
            trigger=request.user,
            trigger_type=WorkflowNodeHistoryCallback.TriggerType.MANUAL,
            callback_type=callback_type,
            callback_url=callback_url,
        )
        try:
            res = callback_work(
                callback_type, 'POST', callback_url,
                creator_id=request.user.id,
                wid='00000000000', topic='测试回调', node_name=data['node'],
                template_id=data['template'],
                cur_node_form={'type': callback_conf['type'], 'comment': '测试'},
                first_node_form=data['form'],
                workflow_node_history_id=0,
                headers=dict(request.headers),
                cookies=dict(request.COOKIES),
                action=action
            )
            cb_obj.response_code = res['response']['code']
            cb_obj.response_result = res['response']['data']
            if cb_obj.response_code != 200:
                if action == 'simulate':
                    # 回调模拟
                    transaction.savepoint_rollback(init_point)
                raise ValueError(cb_obj.response_result)

            response = Response({
                'code': 20000,
                'status': 'success',
                'data': res
            })
        except Exception as e:
            logger.exception(e)
            error = f'回调函数发生异常： {e.__class__} {e}'
            cb_obj.response_result = error
            response = Response({
                'code': 40000,
                'status': 'failed',
                'message': error,
            })
        # 增加回调结果判断
        if cb_obj.response_code == 200:
            cb_obj.status = WorkflowNodeHistoryCallback.Status.SUCCESS
        else:
            cb_obj.status = WorkflowNodeHistoryCallback.Status.ERROR
        cb_obj.response_time = timezone.now()
        cb_obj.save()
        if action == 'simulate':
            # 回调模拟
            transaction.savepoint_rollback(init_point)
        return response

    @action(methods=['POST'], url_path='retry', detail=True)
    def retry(self, request, *args, **kwargs):
        """
        重新触发回调
        """
        workflow_node_history_callback_obj = WorkflowNodeHistoryCallback.objects.get(
            id=kwargs['pk'])
        headers = {
            'Authorization': dict(self.request.headers).get('Authorization')
        }
        cookies = {}
        # 预先初始化好回调数据
        handle_type = workflow_node_history_callback_obj.callback_type
        node_history = workflow_node_history_callback_obj.node_history
        callback_url = workflow_node_history_callback_obj.callback_url
        data = {
            'node_history': node_history,
            'trigger': request.user,
            'trigger_type': WorkflowNodeHistoryCallback.TriggerType.MANUAL,
            'callback_type': handle_type,
            'callback_url': callback_url,
        }
        new_cb_obj = WorkflowNodeHistoryCallback.objects.create(**data)
        taskid = async_task('qtasks.tasks.workflow_callback', handle_type, node_history.id, new_cb_obj.id, 'post', callback_url, headers=headers,
                            cookies=cookies)
        # 重试之后， 把原来的回调状态设置为 已重试
        workflow_node_history_callback_obj.status = WorkflowNodeHistoryCallback.Status.RETRY
        workflow_node_history_callback_obj.save()
        return Response({
            'code': 20000,
            'status': 'success',
            'message': '重新执行完毕',
        })

    def get_queryset(self):
        node_history_id = self.request.query_params.get(
            'node_history_id', None)
        if node_history_id:
            return self.queryset.filter(node_history__id=node_history_id)
        return self.queryset
