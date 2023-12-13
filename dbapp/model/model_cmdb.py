#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
@Author : Charles Lai
@Contact : qqing_lai@hotmail.com
@Time : 2021/05/13 下午12:02
@FileName: model_cmdb.py
@Blog : https://imaojia.com
"""

from dbapp.models import Region, Idc
from dbapp.model.model_ucenter import UserProfile

from common.variables import *
from common.extends.fernet import EncryptedJsonField
from common.extends.models import TimeAbstract, CommonParent


def get_default_labels():
    return {'labe': [], 'selector': [], 'command': ''}


class DevLanguage(TimeAbstract):
    name = models.CharField(max_length=100, unique=True, verbose_name='开发语言')
    alias = models.CharField(max_length=128, default='', verbose_name='别名')
    base_image = models.JSONField(default=dict, verbose_name='基础镜像',
                                  help_text='{"project": "", "project_id": "", "image": "", "tag": ""}')
    build = models.JSONField(default=dict, verbose_name='构建命令')
    dockerfile = models.TextField(
        null=True, blank=True, default='', verbose_name='Dockerfile模板')
    pipeline = models.TextField(
        null=True, blank=True, default='', verbose_name='流水线模板')
    template_k8s = models.TextField(null=True, blank=True, default='', verbose_name='Kubernetes模板',
                                    help_text='从数据字典接口获取,对应项的key为YAML')
    labels = models.JSONField(default=get_default_labels, verbose_name='标签',
                              help_text='{label: [{"name": "name", "value": "value"}], selector: [{"name": "name", "value": "value"}], command: ""}')
    desc = models.TextField(verbose_name='描述', null=True, blank=True)

    def __str__(self) -> str:
        return self.name

    class ExtMeta:
        related = True
        dashboard = True

    class Meta:
        db_table = 'cmdb_devlanguage'
        verbose_name = '开发语言'
        verbose_name_plural = verbose_name + '管理'


class Product(TimeAbstract, CommonParent):
    name = models.CharField(max_length=100, unique=True, verbose_name='产品')
    alias = models.CharField(max_length=128, default='', verbose_name='产品别名')
    region = models.ForeignKey(
        Region, blank=True, null=True, on_delete=models.PROTECT, verbose_name='区域')
    desc = models.TextField(verbose_name='详情描述', null=True, blank=True)
    prefix = models.CharField(
        max_length=100, null=True, blank=True, verbose_name='前缀')
    managers = models.JSONField(default=dict, verbose_name='负责人',
                                help_text='存储格式 对象: {"product": userid, "develop": userid}；product: 产品负责人, develop: 技术负责人；值为int类型，存储用户ID.')

    def __str__(self):
        return self.name

    class ExtMeta:
        related = True
        dashboard = True
        icon = 'asset4'

    class Meta:
        db_table = 'cmdb_product'
        verbose_name = '产品'
        verbose_name_plural = verbose_name + '管理'


class Environment(TimeAbstract):
    """环境"""
    name = models.CharField(max_length=100, unique=True, verbose_name='环境')
    alias = models.CharField(max_length=128, default='', verbose_name='环境别名')
    ticket_on = models.SmallIntegerField(default=0, choices=((0, '不启用'), (1, '启用')), verbose_name='启用工单',
                                         help_text="是否启用工单\n(0, '不启用'), (1, '启用'), 默认: 0")
    merge_on = models.SmallIntegerField(default=0, choices=((0, '不启用'), (1, '启用')), verbose_name='分支合并',
                                        help_text="是否要求分支合并\n(0, '不启用'), (1, '启用'), 默认: 0")
    template = models.JSONField(default=dict, verbose_name='应用配置',
                                help_text='从数据字典接口获取,对应项的key为TEMPLATE, 数据格式为对象.\n对应项的extra属性.\n参数说明:\nstrategy: 策略配置\n  - replicas: 副本, integer\n  - revisionHistoryLimit: 保留副本, integer\n  - minReadySeconds: 更新等待时间, integer\n  - maxSurge/maxUnavailable: 比例缩放  \n\nresources: 资源配额\n - limits.cpu: CPU限制\n - limits.memory: 内存限制\n - requests.cpu: CPU请求\n - requests.memory: 内存请求  \n\nenv: 环境变量, 数组[{"name": "env1", "value": "value1"}]')
    allow_ci_branch = models.JSONField(default=list, verbose_name='允许构建的分支',
                                       help_text="存储数组格式，具体的分支名; 默认['*'], 表示允许所有分支.")
    allow_cd_branch = models.JSONField(default=list, verbose_name='允许发布的分支',
                                       help_text="存储数组格式，具体的分支名; 默认['*'], 表示允许所有分支.")
    extra = models.JSONField(
        default=dict, verbose_name='额外参数', help_text='更多参数')
    desc = models.TextField(null=True, blank=True, verbose_name='环境描述')
    sort = models.IntegerField(default=999, verbose_name="排序标记")

    def __str__(self):
        return self.name

    class ExtMeta:
        related = True
        dashboard = True

    class Meta:
        db_table = 'cmdb_environment'
        ordering = ['sort']
        verbose_name = '环境'
        verbose_name_plural = verbose_name + '管理'


class KubernetesCluster(TimeAbstract):
    """
    K8s集群配置
    """
    name = models.CharField(max_length=100, unique=True, verbose_name='集群名称')
    version = models.JSONField(default=dict, verbose_name='版本',
                               help_text='{"core": "1.14", "apiversion": "apps/v1"}\ncore: 集群版本\napiversion: API版本')
    desc = models.TextField(null=True, blank=True, verbose_name='集群描述')
    config = EncryptedJsonField(default=dict, verbose_name='集群配置')
    environment = models.ManyToManyField(
        Environment, related_name='env_k8s', blank=True, verbose_name='环境')
    product = models.ManyToManyField(
        Product, related_name='product_k8s', blank=True, verbose_name='产品')
    idc = models.ForeignKey(Idc, blank=True, null=True,
                            on_delete=models.PROTECT, verbose_name='IDC')

    def __str__(self):
        return self.name

    class ExtMeta:
        related = True
        dashboard = True
        icon = 'k8s'

    class Meta:
        db_table = 'cmdb_kubernetescluster'
        default_permissions = ()
        ordering = ['-id']
        verbose_name = 'K8s集群'
        verbose_name_plural = verbose_name + '管理'


def get_default_team_members():
    return {
        'op': [],
        'dev': [],
        'test': [],
        'product': [],
        # '特许发版': []
    }


def get_default_dockerfile():
    return {
        'key': 'default', 'value': 'default'
    }


def get_default_value():
    return {
        'key': 'default', 'value': 'default'
    }


class Project(TimeAbstract, CommonParent):
    """项目"""
    projectid = models.CharField(max_length=128, db_index=True, unique=True, verbose_name='项目ID',
                                 help_text='前端无须传值')
    name = models.CharField(max_length=100, verbose_name='项目名称')
    alias = models.CharField(max_length=128, default='', verbose_name='项目别名')
    product = models.ForeignKey(
        Product, on_delete=models.PROTECT, null=True, blank=True, verbose_name="区域")
    creator = models.ForeignKey(UserProfile, on_delete=models.PROTECT, null=True, blank=True, verbose_name='项目创建人',
                                help_text='前端不需要传递')
    manager = models.SmallIntegerField(
        blank=True, null=True, verbose_name='项目负责人')
    developer = models.SmallIntegerField(
        blank=True, null=True, verbose_name='开发负责人')
    tester = models.SmallIntegerField(
        blank=True, null=True, verbose_name='测试负责人')
    desc = models.TextField(verbose_name='描述', null=True, blank=True)
    notify = models.JSONField(default=dict, verbose_name='消息通知')

    def __str__(self):
        return self.name

    class ExtMeta:
        related = True
        dashboard = True
        icon = 'tree-table'

    class Meta:
        db_table = 'cmdb_project'
        verbose_name = '项目'
        verbose_name_plural = verbose_name + '管理'
        default_permissions = ()


class ProjectConfig(TimeAbstract):
    project = models.ForeignKey(
        Project, on_delete=models.PROTECT, verbose_name='项目')
    environment = models.ForeignKey(
        'Environment', on_delete=models.PROTECT, verbose_name='环境')
    template = models.JSONField(default=dict, verbose_name='K8s配置')

    class Meta:
        db_table = 'cmdb_projectconfig'
        verbose_name = '项目配置'
        verbose_name_plural = verbose_name + '管理'
        default_permissions = ()
        unique_together = ('project', 'environment')


class ProjectEnvReleaseConfig(TimeAbstract):
    """
    以项目为维度的额外发布配置
    """

    project = models.ForeignKey(
        Project, on_delete=models.PROTECT, verbose_name='项目')
    environment = models.ForeignKey(
        'Environment', on_delete=models.PROTECT, verbose_name='环境')
    config = models.JSONField(default=dict, verbose_name='配置')

    class Meta:
        db_table = 'cmdb_projectenvreleaseconfig'
        ordering = ['-id']
        unique_together = ('project', 'environment')


class MicroApp(TimeAbstract):
    appid = models.CharField(max_length=250, db_index=True, unique=True, verbose_name='应用ID',
                             help_text='应用唯一标识，无需填写')
    name = models.CharField(max_length=128, verbose_name='应用')
    alias = models.CharField(max_length=128, blank=True, verbose_name='别名')
    project = models.ForeignKey(
        Project, on_delete=models.PROTECT, null=True, blank=True, verbose_name='项目')
    creator = models.ForeignKey(UserProfile, on_delete=models.PROTECT, null=True, blank=True, verbose_name='应用创建人',
                                help_text='前端不需要传递')
    repo = models.JSONField(default=dict, verbose_name='仓库地址',
                            help_text='{"id": id, "name": name, "http_url_to_repo": url}')
    target = models.JSONField(default=get_default_value, verbose_name='JAR包配置',
                              help_text='默认：default, {"default": "default", "custom": "xxx/a.war"}')
    team_members = models.JSONField(
        default=get_default_team_members, verbose_name="团队成员组")
    category = models.CharField(
        max_length=128, blank=True, null=True, verbose_name='应用分类')
    template = models.JSONField(default=dict, verbose_name='应用配置',
                                help_text='从数据字典接口获取,对应项的key为TEMPLATE, 数据格式为对象.\n对应项的extra属性.\n参数说明:\nstrategy: 策略配置\n  - replicas: 副本, integer\n  - revisionHistoryLimit: 保留副本, integer\n  - minReadySeconds: 更新等待时间, integer\n  - maxSurge/maxUnavailable: 比例缩放  \n\nresources: 资源配额\n - limits.cpu: CPU限制\n - limits.memory: 内存限制\n - requests.cpu: CPU请求\n - requests.memory: 内存请求  \n\nenv: 环境变量, 数组[{"name": "env1", "value": "value1"}]\n\ncommand: 启动命令, 字符串')
    language = models.CharField(
        max_length=32, default='java', verbose_name='开发语言')
    build_command = models.CharField(max_length=250, blank=True, null=True, verbose_name='构建命令',
                                     help_text='根据应用开发语言, 从getKey("LANGUAGE")获取数据, 取出extra字段的build值')
    multiple_app = models.BooleanField(
        default=False, blank=True, verbose_name='多应用标志')
    multiple_ids = models.JSONField(default=list, verbose_name='多应用关联ID列表')
    dockerfile = models.JSONField(default=get_default_value, verbose_name='Dockerfile配置',
                                  help_text='默认：{default: null}, 可选: {"default|默认": null, "project|使用项目Dockerfile"： "project", "custom|自定义Dockerfile": ""}')
    online = models.BooleanField(default=True, blank=True, verbose_name='上线下线',
                                 help_text='应用上线/下线状态标记, 下线状态的应用禁止发布.')
    desc = models.TextField(verbose_name='描述', null=True, blank=True)
    notify = models.JSONField(default=dict, verbose_name='消息通知')
    can_edit = models.JSONField(default=list, verbose_name='管理人员',
                                help_text='有权限编辑该应用的人员ID\n格式为数组, 如[1,2]')
    is_k8s = models.CharField(max_length=8, default='k8s', choices=G_DEPLOY_TYPE, verbose_name='部署方式',
                              help_text=f'默认k8s, 可选: {dict(G_DEPLOY_TYPE)}')
    modules = models.JSONField(default=list, verbose_name='工程模块')

    def __str__(self):
        return '[%s]%s' % (self.name, self.alias)

    class ExtMeta:
        related = True
        dashboard = True
        icon = 'component'

    class Meta:
        db_table = 'cmdb_microapp'
        default_permissions = ()
        ordering = ['-created_time']
        verbose_name = '应用'
        verbose_name_plural = verbose_name + '管理'


class AppInfo(TimeAbstract):
    uniq_tag = models.CharField(
        max_length=128, unique=True, verbose_name='唯一标识', help_text='前端留空，无需传值')
    app = models.ForeignKey(MicroApp, blank=True, null=True,
                            on_delete=models.PROTECT, verbose_name='应用')
    environment = models.ForeignKey(
        Environment, on_delete=models.PROTECT, null=True, verbose_name='环境')
    branch = models.CharField(
        max_length=64, blank=True, null=True, verbose_name="构建分支")
    allow_ci_branch = models.JSONField(default=list, verbose_name='允许构建的分支',
                                       help_text="存储数组格式，具体的分支名; 默认['*'], 表示允许所有分支.")
    allow_cd_branch = models.JSONField(default=list, verbose_name='允许发布的分支',
                                       help_text="存储数组格式，具体的分支名; 默认['*'], 表示允许所有分支.")
    build_command = models.CharField(max_length=250, blank=True, null=True, verbose_name='构建命令',
                                     help_text='根据应用开发语言, 从getKey("LANGUAGE")获取数据, 取出extra字段的build值')
    kubernetes = models.ManyToManyField(KubernetesCluster, related_name='k8s_app', through='KubernetesDeploy',
                                        verbose_name='K8s集群')
    hosts = models.JSONField(
        default=list, verbose_name='部署主机', help_text='部署主机, 格式: []')
    version = models.CharField(
        max_length=250, blank=True, null=True, verbose_name='当前版本')
    template = models.JSONField(default=dict, verbose_name='应用配置',
                                help_text='继承自当前应用的template字段,数据格式为对象\n字段说明:\ntype: 0|1, 0表示继承应用模板,template为空字典;1表示自定义模板\n示例: {"type": 0, "template": {}}')
    pipeline = models.JSONField(
        default=dict, verbose_name='流水线', help_text='{"custom": True, "pipeline": {}}')
    is_enable = models.SmallIntegerField(
        default=1, verbose_name='启用', help_text='状态 {0: 禁用， 1： 启用}，默认值为1')
    desc = models.TextField(verbose_name='描述', null=True, blank=True)
    can_edit = models.JSONField(default=list, verbose_name='管理人员',
                                help_text='有权限编辑该应用的人员ID\n格式为数组, 如[1,2]')
    online = models.SmallIntegerField(default=0, choices=G_ONLINE_CHOICE, verbose_name='是否上线',
                                      help_text=f'默认为0,即未上线\n可选项: {G_ONLINE_CHOICE}')

    def __str__(self):
        return self.uniq_tag

    @property
    def namespace(self):
        return f'{self.environment.name.replace("_", "-")}-{self.app.project.product.name.replace("_", "-")}'.lower()

    @property
    def jenkins_jobname(self):
        try:
            job_name = f'{self.environment.name}-{self.app.category.split(".")[-1]}-{self.app.project.name}-{self.app.name.split(".")[-1]}'.lower(
            )
        except AppInfo.DoesNotExist:
            job_name = ''
        return job_name

    class ExtMeta:
        related = True
        dashboard = True

    class Meta:
        db_table = 'cmdb_appinfo'
        default_permissions = ()
        ordering = ['-update_time', '-id']
        verbose_name = '应用模块'
        verbose_name_plural = verbose_name + '管理'


class KubernetesDeploy(TimeAbstract):
    appinfo = models.ForeignKey(
        AppInfo, related_name='app_info', null=True, on_delete=models.CASCADE)
    kubernetes = models.ForeignKey(
        KubernetesCluster, related_name='app_k8s', null=True, on_delete=models.CASCADE)
    online = models.SmallIntegerField(default=0, choices=G_ONLINE_CHOICE, verbose_name='是否上线',
                                      help_text=f'默认为0,即未上线\n可选项: {G_ONLINE_CHOICE}')
    version = models.CharField(
        max_length=250, blank=True, null=True, verbose_name='当前版本')

    def __str__(self):
        return '%s-%s' % (self.appinfo.app.appid, self.kubernetes.name)

    class Meta:
        db_table = 'cmdb_kubernetesdeploy'
        default_permissions = ()
