from django_q.tasks import async_task
from qtasks.tasks import workflow_callback
from common.ext_fun import gitlab_cli
from dbapp.models import UserProfile
from dbapp.models import Workflow, WorkflowNodeHistory, WorkflowNodeHistoryCallback
import logging
from django.db import transaction
from workflow.notice import NoticeProxy

logger = logging.getLogger(__name__)


class LifeCycle(object):
    def __init__(self, request, workflow_obj: Workflow, node_obj: WorkflowNodeHistory, form: dict, is_async=True):
        self.request = request
        self.workflow_obj = workflow_obj
        self.node_obj = node_obj
        self.is_async = is_async
        self.template_obj = self.workflow_obj.template
        self.original_current_node_conf = self.workflow_obj.cur_node_conf
        self.form = form

    def _get_next_node_name(self):
        prev_node_history = WorkflowNodeHistory.objects.filter(
            workflow=self.workflow_obj,
            id__lt=self.node_obj.id
        )
        if prev_node_history.count() > 0:
            prev_node_history = prev_node_history.first()
        try:
            if prev_node_history and prev_node_history.form.get('handle_type') == 'reject':
                node_name = prev_node_history.node
                node_index = self.template_obj.node_list.index(node_name)
            else:
                node_name = self.workflow_obj.node
                node_index = self.template_obj.node_list.index(node_name) + 1
            return self.template_obj.node_list[node_index]
        except IndexError:
            return None

    def _get_node_conf(self, node_name):
        return

    def handle(self, check_form=True):
        """
        流程生命周期流转处理
        :param check_form: 是否检查表单 handle_type 字段, 新增的表单就不需要检查， 直接 next
        :return:
        """
        if not check_form:
            self.node_obj.handle_type = self.node_obj.HandleType.PASSED
            self.next()
        else:
            node_conf = self.template_obj.get_node_conf(self.node_obj.node)
            # passed=通过 reject=驳回
            handle_type = self.form.get('handle_type', 'passed')
            if handle_type == WorkflowNodeHistory.HandleType.PASSED:
                node_conf = self.template_obj.get_node_conf(self.node_obj.node)
                self.node_obj.handle_type = WorkflowNodeHistory.HandleType.PASSED
                if node_conf['pass_type'] != "countersigned":
                    self.next()
                else:
                    members_conf = node_conf['members']
                    member_len = len(members_conf)
                    member_handle_count = 0
                    for member_info in members_conf:
                        member_id = member_info.split('@')[1]
                        user_obj = UserProfile.objects.get(id=member_id)
                        user_node_history_objs = WorkflowNodeHistory.objects.filter(
                            workflow=self.workflow_obj,
                            operator=user_obj,
                            handle_type=WorkflowNodeHistory.HandleType.PASSED
                        )
                        if user_node_history_objs.count() > 0:
                            member_handle_count += 1
                    if member_handle_count >= member_len:
                        self.next()
                    else:
                        self.node_obj.save()
                        self.workflow_obj.save()
                        return
            else:
                self.node_obj.handle_type = self.node_obj.HandleType.REJECT
                self.reject()

        # 保存变更
        self.node_obj.save()
        self.workflow_obj.save()
        transaction.on_commit(
            # 执行回调
            lambda: self.exec_callback()
        )

        transaction.on_commit(
            # 执行回调
            lambda: self.notice()
        )

    def complete(self):
        """
        流程完结
        :return:

        """
        self.workflow_obj.status = self.workflow_obj.STATUS.complete

    def reject(self):
        """
        驳回，
        默认回到第一个节点
        todo 支持选择驳回节点
        :return:
        """
        self.workflow_obj.node = self.template_obj.node_list[0]
        self.workflow_obj.status = self.workflow_obj.STATUS.reject

    def next(self):
        """
        流转到下一个节点
        :return:
        """
        next_node_name = self._get_next_node_name()
        if not next_node_name:
            return self.complete()
        self.workflow_obj.node = next_node_name

    def exec_callback(self):
        """
        判断当前节点的 处理类型

        如果是 驳回， 则执行驳回的回调
        如果是通过， 则执行通过的回调
        最后检查是否有 提交后执行的回调， 一并执行了
        :return:
        """

        handle_type = self.node_obj.handle_type
        node_callbacks_conf = self.original_current_node_conf.get(
            'callbacks', [])
        cb = Callback(
            self.request,
            self.node_obj,
            self.original_current_node_conf,
            handle_type,
            node_callbacks_conf,
            is_async=self.is_async
        )
        cb.run()

    def notice(self):
        n = NoticeProxy(self.workflow_obj, self.node_obj,
                        send_async=self.is_async)
        n.run()


class Callback(object):
    def __init__(self, request, node_obj, node_conf, handle_type, callbacks_info, is_async=True):
        self.request = request
        self.node_obj = node_obj
        self.node_conf = node_conf
        self.handle_type = handle_type
        self.callbacks_info = callbacks_info or []
        self.is_async = is_async
        self.group_by_info = self.group_by()
        self.func = self.get_func()

    def run(self):
        if not self.callbacks_info:
            logger.debug(f'节点 {self.node_conf["name"]} 不存在回调， 忽略执行')
            return

        handle_type_callbacks = self.group_by_info.get(self.handle_type)
        logger.debug(f'handle_type_cbs= ==== {handle_type_callbacks}')

        for callback_info in self.callbacks_info:
            t = callback_info['type']
            if t == self.handle_type or t == 'all':
                self.call_func(t, callback_info['url'])

    def call_func(self, handle_type, url):
        headers = {
            'Authorization': dict(self.request.headers).get('Authorization')
        }
        cookies = {}
        # 预先初始化好回调数据
        data = {
            'node_history': self.node_obj,
            'trigger': self.node_obj.operator,
            'trigger_type': WorkflowNodeHistoryCallback.TriggerType.AUTO,
            'callback_type': self.handle_type,
            'callback_url': url,
        }
        cb_obj = WorkflowNodeHistoryCallback.objects.create(**data)
        self.func(handle_type, self.node_obj.id, cb_obj.id,
                  'post', url, headers=headers, cookies=cookies)

    @staticmethod
    def async_func(*args, **kwargs):
        taskid = async_task(f'qtasks.tasks.workflow_callback', *args, **kwargs)

    def get_func(self):
        func = workflow_callback
        if self.is_async:
            func = self.async_func
        return func

    def group_by(self):
        """
        根据 回调类型进行归类
        :return:
        """
        group = {}
        for callback_info in self.callbacks_info:
            t = callback_info['type']
            if t not in group:
                group[t] = []
            group[t].append(callback_info)
        return group
