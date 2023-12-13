from datetime import datetime

from django_q.tasks import async_task, AsyncTask
from common.ext_fun import get_redis_data, time_convert
from dbapp.models import UserProfile, Organization
from dbapp.models import PublishOrder
from dbapp.models import Workflow, WorkflowNodeHistory
from django.template import Context, Template
from django.conf import settings

import logging

logger = logging.getLogger('api')


def get_member_user_ids(members: list):
    user_ids = set()
    for member_str in members:
        member_type, member_id, _ = member_str.split('@')
        if member_type == 'user':
            user_ids.add(member_id)
            continue
        if member_type == 'organization':
            org_obj = Organization.objects.filter(id=member_id)
            if org_obj.count() == 0:
                logger.warning(f'未能识别的部门ID：{member_id}')
                continue
            org_obj = org_obj.first()
            cur_user_ids = list(UserProfile.objects.filter(
                department__id=org_obj.id).values_list('id', flat=True))
            for i in cur_user_ids:
                user_ids.add(i)
    return list(set(user_ids))


class NoticeProxy(object):
    def __init__(self, workflow_obj: Workflow, node_obj: WorkflowNodeHistory, send_async=True):
        """
        工单通知类
        """
        self.workflow_obj = workflow_obj
        self.node_obj = node_obj
        self.send_async = send_async

        self.topic = workflow_obj.topic
        self.workflow_template_name = workflow_obj.template.name
        self.status = workflow_obj.get_status_display()
        platform_config = get_redis_data('platform')
        domain_url = platform_config['url']

        # 生成便捷链接
        self.handle_url = f'{domain_url}#/workflow/workbench/{workflow_obj.wid}/handle?node={self.workflow_obj.node}'
        self.detail_url = f'{domain_url}#/workflow/workbench/{workflow_obj.wid}/detail'

        self.notice_class = [
            NoticeClsBase
        ]

    def run(self):
        """
        如果是被驳回的话， 处理人员通知的是发起人
        节点处理后， 通知下一个节点的处理成员 | 通知成员
        如果节点是最后一个节点， 处理后工单是完成状态， 则通知发起人。
        :return:
        """
        cur_node_conf = self.workflow_obj.cur_node_conf
        members = cur_node_conf.get('members', [])
        notice_members = cur_node_conf.get('notice_members', [])
        prev_node_obj = WorkflowNodeHistory.objects.filter(
            workflow=self.workflow_obj, id__lt=self.node_obj.id).first()

        is_over = self.workflow_obj.status == Workflow.STATUS.complete
        if self.node_obj.handle_type == 'reject':
            members = [
                f'user@{self.workflow_obj.creator.id}@{self.workflow_obj.creator.first_name}']
        elif prev_node_obj and prev_node_obj.handle_type == 'reject':
            _members = [
                f'user@{prev_node_obj.operator.id}@{prev_node_obj.operator.first_name}']
            node_conf = self.workflow_obj.template.get_node_conf(
                prev_node_obj.node)
            if node_conf.get('pass_type', '') == 'countersigned':
                # 获取所有未处理人员, 因为已处理的无需重复再通知处理
                for member in members:
                    member_id = member.split('@')[1]
                    already_handle = WorkflowNodeHistory.objects.filter(
                        workflow=self.workflow_obj,
                        node=prev_node_obj.node,
                        operator__id=member_id,
                        handle_type=WorkflowNodeHistory.HandleType.PASSED
                    ).count() > 0
                    # 如果没有处理记录， 则添加进去
                    if not already_handle:
                        _members.append(member)
            members = _members
        members = list(set(members))
        notice_members = list(set(notice_members))
        for cls in self.notice_class:
            try:
                logger.debug(f'cls=== {cls}')
                notice_obj = cls(self, members, notice_members,
                                 send_async=self.send_async)
                notice_obj.notice_notice()
            except Exception as e:
                logger.debug(f'调用通知类 {cls} 发生错误 {e.__class__} {e}')


class NoticeClsBase(object):
    # 为了测试方便， 默认使用邮件
    notice_func = None

    def __init__(self, notice_obj, members, notice_members, send_async=True):
        self.notice_obj = notice_obj
        self.members = members
        self.notice_members = notice_members
        self.send_async = send_async

        # 如果是异步模式， 则使用 xxx.delay() 调用 celery
        if send_async is True:
            self.func = self.async_func
        else:
            self.func = self.notice_func

    def async_func(self, *args):
        taskid = async_task(f'qtasks.tasks.{self.notice_func.__name__}', *args)

    def get_content(self, title, readonly=False):
        member_name_list = []
        notice_member_name_list = []
        for i in self.members:
            _, _, name = i.split('@')
            member_name_list.append(name)

        for j in self.notice_members:
            _, _, name = j.split('@')
            notice_member_name_list.append(name)

        notice_msg_template = """
        <!DOCTYPE html>
        <html lang="">
        <head>
        <meta charset="utf-8" />
        <meta http-equiv="X-UA-Compatible" content="IE=edge" />
        <meta name="viewport" content="width=device-width,initial-scale=1.0" />
        <title>{{title}}</title>
        <style>
          ul,
          li {
            padding: 0;
            margin: 0;
          }
          body {
            overflow-x: hidden;
            overflow-y: hidden;
          }
          .container {
            height: 100%;
            border: 10px solid #e9ebec;
            padding-bottom: 20px;
          }
          .jump {
            display: block;
            margin: 5px 0 5px 40px;
          }
          .container ul li {
            margin-bottom: 5px;
          }
          .container ul {
            margin-left: 40px;
            margin-top: 10px;
          }
          .hr {
            width: 100%;
            height: 1px;
            background-color: #a8a8a8;
          }
        </style>
        </head>
        <body>
        <div class="container">
          <h3 style="margin-left: 25px">{{title}}</h3>
          <div class="hr"></div>
          <ul style="margin-top: 20px">
            <li>标题：{{topic}}</li>
            <li>工单ID：{{wid}}</li>
            <li>工单状态：{{status}}</li>
            <li>创建时间：{{created_time}}</li>
            <li>申请人：{{creator}}</li>
            <li>处理节点：{{node}}</li>
            <li>处理成员：{{members}}</li>
          </ul>
          {% if not readonly %}
            <a href="{{handle_url}}" target="_blank" class="jump">点击处理</a>
          {% endif %}
          <ul>
            <li>通知成员：{{notice_members}}</li>
          </ul>
          <a href="{{detail_url}}" class="jump" target="_blank">点击查看</a>
        </div>
        </body>
        </html>
                """
        t = Template(notice_msg_template)
        c = Context({
            'title': title,
            'topic': self.notice_obj.workflow_obj.topic,
            'wid': self.notice_obj.workflow_obj.wid,
            'status': self.notice_obj.workflow_obj.get_status_display(),
            'created_time': datetime.strftime(self.notice_obj.workflow_obj.created_time, settings.DATETIME_FORMAT),
            'creator': self.notice_obj.workflow_obj.creator.first_name or self.notice_obj.workflow_obj.creator.username,
            'node': self.notice_obj.workflow_obj.node,
            'members': ', '.join(member_name_list),
            'handle_url': self.notice_obj.detail_url,
            'notice_members': notice_member_name_list and ', '.join(notice_member_name_list) or '无',
            'detail_url': self.notice_obj.detail_url,
            'readonly': readonly,
        })
        html = t.render(c)
        return html

    def notice_handle(self):
        """
        待处理通知
        :return:
        """
        title = '您有一个工单需要处理'
        content = self.get_content(title)
        member_ids = get_member_user_ids(self.members)
        member_objs = UserProfile.objects.filter(
            id__in=member_ids
        ).values_list('email', flat=True)
        if not member_objs:
            return
        self.func(self.get_title(title), content, ','.join(member_objs))

    def notice_notice(self):
        """
        通知抄送
        :return:
        """
        title = '工单处理通知'
        content = self.get_content(title, readonly=True)
        notice_member_ids = get_member_user_ids(self.notice_members)
        member_objs = UserProfile.objects.filter(
            id__in=notice_member_ids
        ).values_list('email', flat=True)
        if not member_objs:
            return
        self.func(self.get_title(title), content, ','.join(member_objs))

    def notice_complete(self):
        """
        工单办结通知
        工单是完成状态， 则通知发起人
        :return:
        """
        title = '工单办结通知'
        content = self.get_content(title, readonly=True)
        member_ids = get_member_user_ids(self.members)
        member_objs = UserProfile.objects.filter(
            id__in=member_ids
        ).values_list('email', flat=True)
        if not member_objs:
            return
        self.func(self.get_title(title), content, ','.join(member_objs))

    def get_title(self, title):
        return f'{title} #{self.notice_obj.workflow_obj.wid}'
