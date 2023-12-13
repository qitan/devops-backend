#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
@Author : Charles Lai
@Contact : qqing_lai@hotmail.com
@Time : 2020/9/24 下午2:06
@FileName: models.py
@Blog ：https://imaojia.com
"""

from tabnanny import verbose
from django.db import models
from rest_framework.compat import unicode_http_header
from cmdb import model

from dbapp.model.model_ucenter import UserProfile
from dbapp.models import AppInfo, Environment

from common.variables import *
from common.extends.models import TimeAbstract, JobManager


class DockerImage(TimeAbstract):
    appid = models.CharField(max_length=250, default='0',
                             verbose_name='应用标识', help_text='应用唯一标识，无需填写')
    app_id = models.IntegerField(
        default=0, verbose_name='应用ID', help_text='Int, MicroApp ID')
    job_id = models.IntegerField(default=0, verbose_name='构建ID')
    image = models.CharField(max_length=250, default=None,
                             unique=True, verbose_name='容器镜像')
    deployer = models.ForeignKey(UserProfile, verbose_name='操作者', blank=True, null=True,
                                 default=None, on_delete=models.SET_NULL)
    commits = models.JSONField(default=dict, verbose_name='提交信息')
    delete_flag = models.SmallIntegerField(default=0, choices=G_IMAGE_FLAG,
                                           verbose_name=f'镜像删除标记\n{dict(G_IMAGE_FLAG)}')

    def __str__(self) -> str:
        return self.image

    class Meta:
        db_table = 'deploy_dockerimage'
        default_permissions = ()
        ordering = ['-update_time', '-id']


class BuildJob(TimeAbstract):
    """
    持续构建模型
    """
    order_id = models.IntegerField(default=0, verbose_name='发布工单ID')
    appid = models.CharField(max_length=250, default='0',
                             verbose_name='应用ID', help_text='应用唯一标识，无需填写')
    appinfo_id = models.IntegerField(
        default=0, db_index=True, verbose_name='应用模块ID')
    deployer = models.ForeignKey(UserProfile, verbose_name='发布人', blank=True, related_name='deployer', null=True,
                                 default=None, on_delete=models.SET_NULL)
    # {0: 未构建, 1: 构建成功, 2: 构建失败, 3: 构建中, 4: 作废}
    status = models.SmallIntegerField(default=3, choices=G_CI_STATUS, verbose_name="状态",
                                      help_text=f"状态值: {dict(G_CI_STATUS)}")
    queue_number = models.IntegerField(default=0, verbose_name='队列ID')
    build_number = models.IntegerField(default=0, verbose_name='构建ID')
    commits = models.JSONField(default=dict, verbose_name='提交信息')
    commit_tag = models.JSONField(default=dict, verbose_name='提交类型',
                                  help_text='label可选: heads|tags\nname: 具体的分支或者标签\n{"label": "heads", "name": "master"}')
    # {0: 构建， 1: 构建发布}
    is_deploy = models.SmallIntegerField(default=0, verbose_name='构建发布',
                                         help_text='是否构建完后进行发布, {0: 不发布, 1: 发布}')
    jenkins_flow = models.TextField(
        verbose_name='jenkins pipeline', blank=True, null=True, default="")
    image = models.CharField(max_length=250, blank=True,
                             null=True, verbose_name='容器镜像')
    sync_status = models.SmallIntegerField(default=0, choices=G_IMAGE_SYNC_STAT, verbose_name='镜像同步状态',
                                           help_text=f"{dict(G_IMAGE_SYNC_STAT)}, 默认0")
    modules = models.CharField(
        max_length=250, blank=True, null=True, verbose_name='工程模块')
    batch_uuid = models.CharField(
        max_length=40, null=True, blank=True, verbose_name='批量部署标识')

    @property
    def job_name(self):
        try:
            appinfo_obj = AppInfo.objects.get(id=self.appinfo_id)
            job_name = f'{appinfo_obj.environment.name}-{appinfo_obj.app.category.split(".")[-1]}-{appinfo_obj.app.project.name}-{appinfo_obj.app.name.split(".")[-1]}'.lower(
            )
        except AppInfo.DoesNotExist:
            job_name = ''
        return job_name

    def __str__(self):
        return '%s-%s-%s' % (self.order_id, self.appinfo_id, self.image)

    class Meta:
        db_table = 'deploy_buildjob'
        default_permissions = ()
        ordering = ['-id']


class BuildJobResult(TimeAbstract):
    """
    CI结果
    """
    job_id = models.IntegerField(default=0, db_index=True, verbose_name='任务ID')
    result = models.JSONField(default=dict, verbose_name='构建结果')
    console_output = models.TextField(default='', verbose_name='控制台输出结果')

    class Meta:
        db_table = 'deploy_buildjobresult'
        default_permissions = ()
        ordering = ['-id']


class DeployJob(TimeAbstract):
    """
    持续部署模型
    """
    uniq_id = models.CharField(
        max_length=250, unique=True, verbose_name='发布ID')
    order_id = models.CharField(max_length=40, null=True, blank=True, verbose_name=u'工单号',
                                help_text='前端不需要传值')
    appid = models.CharField(max_length=250, default='0',
                             verbose_name='应用ID', help_text='应用唯一标识，无需填写')
    appinfo_id = models.IntegerField(
        default=0, db_index=True, verbose_name='应用模块ID')
    deployer = models.ForeignKey(UserProfile, verbose_name='发布人', blank=True, related_name='cd_deployer', null=True,
                                 default=None, on_delete=models.SET_NULL)
    status = models.SmallIntegerField(default=0, choices=G_CD_STATUS, verbose_name="状态",
                                      help_text=f'部署状态: {dict(G_CD_STATUS)}, 默认0')
    image = models.CharField(max_length=250, blank=True,
                             null=True, verbose_name='容器镜像')
    kubernetes = models.JSONField(default=list, verbose_name='部署集群',
                                  help_text='待发布集群\n格式为array, 存储集群id, eg: [1,2]')
    deploy_type = models.SmallIntegerField(default=0, choices=G_CD_TYPE, verbose_name='部署类型',
                                           help_text=f"{dict(G_CD_TYPE)}, 默认0")
    rollback_reason = models.SmallIntegerField(null=True, blank=True,
                                               verbose_name='回滚原因')  # 具体类型查看 datadict 的 ROLLBACK_TYPE
    rollback_comment = models.TextField(
        null=True, blank=True, default='', verbose_name='回滚备注')
    modules = models.CharField(
        max_length=250, blank=True, null=True, verbose_name='工程模块')
    batch_uuid = models.CharField(
        max_length=40, null=True, blank=True, verbose_name='批量部署标识')

    @property
    def job_name(self):
        try:
            appinfo_obj = AppInfo.objects.get(id=self.appinfo_id)
            job_name = f'{appinfo_obj.environment}-{appinfo_obj.app.category.split(".")[-1]}-{appinfo_obj.app.project.name}-{appinfo_obj.app.name.split(".")[-1]}'.lower(
            )
        except AppInfo.DoesNotExist:
            job_name = ''
        return job_name

    def __str__(self) -> str:
        return self.uniq_id

    class Meta:
        db_table = 'deploy_deployjob'
        default_permissions = ()
        ordering = ['-id']


class DeployJobResult(TimeAbstract):
    """
    CI结果
    """
    job_id = models.IntegerField(default=0, db_index=True, verbose_name='任务ID')
    result = models.JSONField(default=dict, verbose_name='部署结果')

    class Meta:
        db_table = 'deploy_deployjobresult'
        default_permissions = ()
        ordering = ['-id']


class PublishApp(TimeAbstract):
    """
    发布工单待发布应用
    """
    order_id = models.CharField(
        max_length=40, verbose_name=u'工单号', help_text='前端不需要传值')
    appid = models.CharField(max_length=250, default='0',
                             verbose_name='应用ID', help_text='应用唯一标识，无需填写')
    appinfo_id = models.IntegerField(
        default=0, verbose_name='应用模块ID, AppInfo id')
    name = models.CharField(max_length=128, verbose_name='应用名称')
    alias = models.CharField(max_length=128, verbose_name='应用别名')
    project = models.CharField(
        max_length=128, default='', verbose_name='项目', help_text='项目唯一ID, projectid')
    product = models.CharField(max_length=128, default='',
                               verbose_name='产品', help_text='产品名称, name')
    category = models.CharField(
        max_length=128, blank=True, null=True, verbose_name='应用分类')
    environment = models.IntegerField(
        null=True, blank=True, verbose_name='应用环境', help_text="应用环境ID")
    branch = models.CharField(max_length=64, null=True,
                              blank=True, verbose_name='构建分支')
    image = models.CharField(max_length=250, blank=True,
                             null=True, verbose_name='容器镜像')
    commits = models.JSONField(default=dict, verbose_name='提交信息')
    deploy_type = models.CharField(
        max_length=50, null=True, blank=True, verbose_name='部署类型')
    deploy_type_tag = models.SmallIntegerField(default=0, choices=G_CD_TYPE, verbose_name='部署类型标识',
                                               help_text=f"{dict(G_CD_TYPE)}, 默认0")
    status = models.SmallIntegerField(default=0, choices=G_ORDER_STATUS, verbose_name='发布状态',
                                      help_text=f'发布状态:\n{G_ORDER_STATUS}')
    delete_flag = models.BooleanField(
        default=False, blank=False, verbose_name='逻辑删除')
    modules = models.CharField(
        max_length=250, blank=True, null=True, verbose_name='工程模块')

    def __str__(self):
        return '%s-%s-%s' % (self.order_id, self.appinfo_id, self.name)

    class Meta:
        db_table = 'deploy_publishapp'
        verbose_name = '待发布应用'
        verbose_name_plural = verbose_name + '管理'
        default_permissions = ()


class PublishOrder(TimeAbstract):
    """
    发布工单，关联工单审批
    """
    order_id = models.CharField(
        max_length=40, unique=True, verbose_name=u'工单号', help_text='前端不需要传值')
    dingtalk_tid = models.CharField(max_length=250, default=None, null=True, blank=True, verbose_name='钉钉工单ID',
                                    help_text='填写钉钉流程单号, 可为空')
    title = models.CharField(default='', max_length=250, verbose_name=u'标题')
    category = models.SmallIntegerField(default=0, choices=G_TICKET_TYPE, verbose_name='发版类型',
                                        help_text=f'可选： {G_TICKET_TYPE}')
    creator = models.ForeignKey(UserProfile, null=True, related_name='publish_creator', on_delete=models.SET_NULL,
                                verbose_name=u'工单创建人')
    node_name = models.CharField(
        max_length=50, blank=True, null=True, verbose_name='节点')
    content = models.TextField(default='', verbose_name=u'变更内容')
    formdata = models.JSONField(default=dict, verbose_name='上线表单')
    effect = models.TextField(blank=True, null=True, verbose_name=u'影响')
    environment = models.IntegerField(
        null=True, blank=True, verbose_name='应用环境', help_text="应用环境ID")
    apps = models.ManyToManyField(
        PublishApp, related_name='publish_apps', verbose_name='待发布应用')
    app = models.JSONField(default=list, verbose_name='应用服务',
                           help_text='工单未审核通过, 展示关联的待发布应用.\n格式为数组, 存放应用ID, 如[1, 2]')
    # {0: 未构建, 1: 构建成功, 2: 构建失败, 3: 构建中, 4: 作废/中止}
    status = models.SmallIntegerField(default=0, choices=G_ORDER_STATUS, verbose_name='发布单状态',
                                      help_text=f'工单状态:\n{G_ORDER_STATUS}')
    result = models.TextField(blank=True, null=True,
                              verbose_name=u'处理结果', help_text='前端无需传值')
    expect_time = models.DateTimeField(
        verbose_name='期望发布时间', default=None, null=True)
    executor = models.ForeignKey(UserProfile, null=True, related_name='publish_executor', on_delete=models.SET_NULL,
                                 help_text='前端不需要传值')
    deploy_time = models.DateTimeField(
        verbose_name='发布时间', default=None, null=True)
    method = models.CharField(max_length=6, default='manual',
                              verbose_name='发版方式', help_text='{manual: 手动, auto: 自动, plan: 定时}')
    team_members = models.JSONField(default=list, verbose_name='团队人员')
    extra_deploy_members = models.JSONField(
        default=list, verbose_name='额外指定发布人员')

    def __str__(self):
        return str(self.title)

    class Meta:
        db_table = 'deploy_publishorder'
        default_permissions = ()
        verbose_name = '发布工单'
        verbose_name_plural = verbose_name + '管理'
        ordering = ['-created_time']
