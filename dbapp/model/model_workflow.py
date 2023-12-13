"""
@Author : Ken Chen
@Contact : 316084217@qq.com
@Time : 2021/11/2 上午9:50
"""
from datetime import datetime

import shortuuid
from django.db import models
from dbapp.model.model_cmdb import Environment

from common.extends.models import CreateTimeAbstract, CommonParent
from dbapp.model.model_ucenter import UserProfile
from dbapp.models import TimeAbstract
from markdown import Markdown


class WorkflowCategory(models.Model):
    """
    工单模板分组
    """
    name = models.CharField(max_length=80, unique=True, verbose_name='分类名')
    desc = models.TextField(verbose_name='描述', null=True, blank=True)
    sort = models.IntegerField(default=999, verbose_name='排序')

    def __str__(self):
        return self.name

    class Meta:
        db_table = 'workflow_workflowcategory'
        ordering = ['sort']


class WorkflowTemplateAbstract(TimeAbstract):
    """
    工单模板 抽象类
    """
    category = models.ForeignKey(
        WorkflowCategory, null=True, verbose_name='所属分类', on_delete=models.SET_NULL)
    name = models.CharField(max_length=100, unique=True, verbose_name='工单模板名')
    products = models.JSONField(
        default=list, verbose_name='关联产品', help_text='存储产品ID')
    projects = models.JSONField(default=list, verbose_name='关联项目',
                                help_text='产品项目ID数组, eg: [[product_id, project_id]]')
    environment = models.ForeignKey(
        Environment, on_delete=models.SET_NULL, null=True, blank=True, verbose_name='关联环境')
    enabled = models.BooleanField(default=True, verbose_name='是否启用')
    nodes = models.JSONField(verbose_name='节点配置')
    revision = models.IntegerField(
        default=0, verbose_name='版本号')  # 模板每次变更， 更新版本号加 1
    comment = models.CharField(
        max_length=100, null=True, blank=True, verbose_name='模板备注')
    sort = models.IntegerField(default=999, verbose_name='排序')

    @property
    def node_list(self):
        return [i['name'] for i in self.nodes]

    def get_node_conf(self, node_name):
        node_index = self.node_list.index(node_name)
        return self.nodes[node_index]

    class Meta:
        abstract = True
        ordering = ['sort']

    def __str__(self):
        return self.name


class WorkflowTemplate(WorkflowTemplateAbstract):
    """
    工单模板
    """

    class Meta:
        db_table = 'workflow_workflowtemplate'


class WorkflowTemplateRevisionHistory(WorkflowTemplateAbstract):
    """
    工单模板版本历史保存
    创建工单的时候检查当前模板版本号是否在本模型中存在
    如果不存在， 从 TicketTemplate 复制一份到这边。
    """
    name = models.CharField(max_length=100, verbose_name='工单模板名')

    class Meta:
        db_table = 'workflow_workflowtemplaterevisionhistory'


class Workflow(TimeAbstract):
    """
    工单
    """

    class STATUS:
        close = '已关闭'
        revoke = '已撤回'
        reject = '被驳回'
        wait = '待处理'
        complete = '已完成'
        failed = '执行失败'

        choices = (
            (close, close),
            (revoke, revoke),
            (reject, reject),
            (wait, wait),
            (complete, complete),
            (failed, failed)
        )

    wid = models.CharField(max_length=40, null=True, blank=True, unique=True, verbose_name='工单号',
                           help_text='前端不需要传值')
    topic = models.CharField(max_length=200, verbose_name='工单标题')
    node = models.CharField(max_length=50, verbose_name='当前节点名')
    status = models.CharField(
        max_length=30, choices=STATUS.choices, verbose_name='工单状态')
    creator = models.ForeignKey(
        UserProfile, null=True, on_delete=models.SET_NULL, verbose_name='发起人')
    template = models.ForeignKey(
        WorkflowTemplateRevisionHistory, verbose_name='模板副本', on_delete=models.PROTECT)
    comment = models.CharField(
        max_length=200, null=True, blank=True, verbose_name='备注')
    extra = models.JSONField(default=dict, verbose_name='扩展数据')
    workflow_flag = models.CharField(
        max_length=8, default='normal', verbose_name='工单标记', help_text='normal: 普通, app: 发版应用, sql: SQL工单')

    @property
    def cur_node_conf(self):
        for node_conf in self.template.nodes:
            if node_conf['name'] == self.node:
                return node_conf

    def generate_wid(self, save=False):
        st = shortuuid.ShortUUID()
        st.set_alphabet("0123456789")
        self.wid = f"{datetime.now().strftime('%Y%m%d%H%M%S')}{st.random(length=3)}"
        if save is True:
            self.save()

    class Meta:
        db_table = 'workflow_workflow'
        ordering = ['-id']

    def __str__(self):
        return f'{self.template.id}@{self.template.name}-{self.topic}#{self.wid}-{self.status}'


class WorkflowNodeHistory(models.Model):
    """
    已处理的节点历史记录
    """

    class HandleType(models.TextChoices):
        """
        触发类型
        """
        PASSED = 'passed', '通过'
        REJECT = 'reject', '驳回'
        REVOKE = 'revoke', '撤回'
        CLOSE = 'close', '关闭'
        ERROR = 'error', '回调错误'

    workflow = models.ForeignKey(
        Workflow, on_delete=models.PROTECT, verbose_name='所属工单')
    node = models.CharField(max_length=50, verbose_name='节点')
    handle_type = models.CharField(
        max_length=50, null=True, choices=HandleType.choices, verbose_name='操作类型')
    operator = models.ForeignKey(
        UserProfile, null=True, on_delete=models.SET_NULL, verbose_name='操作人')
    form = models.JSONField(blank=True, null=True, verbose_name='表单数据')
    created_time = models.DateTimeField(
        auto_now_add=True, null=True, blank=True, verbose_name='创建时间')

    @property
    def node_conf(self):
        for node in self.workflow.template.nodes:
            if node['name'] == self.node:
                return node

    def __str__(self):
        return f'{self.workflow.topic}-{self.node}'

    class Meta:
        db_table = 'workflow_workflownodehistory'
        ordering = ['-id']


class WorkflowNodeHistoryCallback(CreateTimeAbstract):
    """
    工单回调信息表
    记录所有工单节点在执行后触发的回调， 以及回调的相关信息
    """

    class TriggerType(models.TextChoices):
        """
        触发类型
        """
        AUTO = 'auto', '自动'
        MANUAL = 'manual', '手动'

    class CallbackType(models.TextChoices):
        """
        回调类型
        """
        ALL = 'all', '提交后调用'
        PASSED = 'passed', '通过后调用'
        REJECT = 'reject', '驳回后调用'

    class Status(models.TextChoices):
        """
        回调类型
        """
        PENDING = 'pending', '待响应'
        ERROR = 'error', '执行出错'
        SUCCESS = 'success', '执行成功'
        RETRY = 'retry', '已重试'

    node_history = models.ForeignKey(WorkflowNodeHistory, null=True, blank=True, on_delete=models.PROTECT,
                                     verbose_name='节点历史')
    trigger = models.ForeignKey(
        UserProfile, null=True, on_delete=models.SET_NULL, verbose_name='触发人')
    callback_url = models.CharField(max_length=250, verbose_name='回调URL')
    callback_type = models.CharField(
        max_length=250, choices=CallbackType.choices, verbose_name='回调类型')
    trigger_type = models.CharField(
        max_length=50, choices=TriggerType.choices, verbose_name='触发类型')
    status = models.CharField(
        max_length=50, default=Status.PENDING, choices=Status.choices, verbose_name='响应状态码')
    response_code = models.IntegerField(default=0, verbose_name='响应状态码')
    response_result = models.TextField(default='', verbose_name='回调结果')
    response_time = models.DateTimeField(
        null=True, blank=True, verbose_name='响应时间')

    class Meta:
        db_table = 'workflow_workflownodehistorycallback'
        ordering = ['-id']
