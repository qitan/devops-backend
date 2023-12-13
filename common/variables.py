#!/usr/bin/env python
# -*- encoding: utf-8 -*-
'''
@Author  :    Charles Lai
@Contact :    qqing_lai@hotmail.com
@Time    :    2021
@FileName:    variables.py
@Blog    :    https://imaojia.com
'''

from elasticsearch_dsl import analyzer, tokenizer, normalizer, Nested
from elasticsearch_dsl import (
    Binary,
    Boolean,
    Byte,
    Completion,
    CustomField,
    Date,
    DateRange,
    DenseVector,
    Double,
    DoubleRange,
    Field,
    Float,
    FloatRange,
    GeoPoint,
    GeoShape,
    HalfFloat,
    Integer,
    IntegerRange,
    Ip,
    IpRange,
    Join,
    Keyword,
    Long,
    LongRange,
    Murmur3,
    Nested,
    Object,
    Percolator,
    RangeField,
    RankFeature,
    RankFeatures,
    ScaledFloat,
    SearchAsYouType,
    Short,
    SparseVector,
    Text,
    TokenCount,
    construct_field,
)
from rest_framework import serializers
from django.db import models
from common.extends.serializers import BooleanField

from dateutil.rrule import YEARLY, MONTHLY, WEEKLY, DAILY, HOURLY, MINUTELY, SECONDLY

# 变量定义

IDC_TYPE = (
    (0, '物理机房'), (1, '公有云')
)
IDC_SUPPLIER = (
    (0, '物理机房'), (1, '阿里云'), (2, '华为云')
)

# 团队成员字段
TEAM_MEMBER = ['op_members', 'dev_members', 'test_members', 'product_members']

WORKLOAD_CHOICE = (('deployment', '无状态'),
                   ('stateful', '有状态'), ('daemonset', '守护进程集'))
SERVICE_CHOICE = ((0, 'NodePort'), (1, 'Ingress'))

# 应用部署方式
G_DEPLOY_TYPE = (
    ('nonk8s', '非Kubernetes部署'),
    ('docker', 'Docker部署'),
    ('k8s', 'Kubernetes部署')
)
# 应用权限申请状态
G_APP_PERM_STATUS = (
    (0, '未处理'),
    (1, '申请通过'),
    (2, '驳回申请')
)

G_ONLINE_CHOICE = (
    (0, '未上线'),
    (1, '已上线'),
    (2, '部署中'),
    (3, '部署异常'),
    (9, '已申请上线'),
    (10, '已下线')
)

G_TICKET_STATUS = (
    (1, '待提交'),
    (2, '审批中'),
    (3, '确认中'),
    (4, '执行中'),
    (5, '客户确认中'),
    (6, '审批不通过,等待客户确认'),
    (7, '确认不通过,等待客户确认'),
    (8, '客户确认不通过,等待执行重做'),
    (9, '已关闭')
)
G_TICKET_LOG = (
    (1, '申请通过'),
    (0, '驳回申请'),
    (2, '重新提交'),
    (4, '执行中'),
    (5, '执行完成'),
    (7, '驳回申请'),
    (8, '用户确认不通过,等待执行重做'),
    (9, '用户结单')
)
G_TICKET_LEVEL = (
    (0, '低'),
    (1, '中'),
    (2, '高'),
    (9, '一般')
)
G_TICKET_TYPE = (
    (0, '常规发布'),
    (1, 'BUG修复'),
    (2, '紧急发布'),
    (9, '应用上线')
)
G_TICKET_AUDIT = (
    (0, '待审核'),
    (1, '审核通过'),
    (2, '驳回')
)

G_DEPLOY_STATUS = (
    ('1', '待审批'),
    ('2', 'SQL 待执行'),
    ('3', 'Apollo 待配置'),
    ('4', '待发布'),
    ('5', '成功'),
    ('6', '失败'),
    ('7', '不通过'),
    ('8', '驳回'),
    ('9', '作废'),
    ('10', '发布中'),
    ('12', '发布完成'),
    ('13', '待验收'),
    ('14', '发布失败')
)
# {0: 未构建, 1: 构建成功, 2: 构建失败, 3: 构建中, 4: 作废}
G_ORDER_STATUS = (
    (0, '待发版'), (1, '发版成功'), (2, '发版失败'), (3,
                                           '发版中'), (4, '作废'), (11, '部分发版成功'), (12, '部分发版失败'),
    (13, '验收不通过'), (14, '验收不通过已回退'))

# 保持顺序一致性
G_COMMIT = (('heads', '分支'), ('tags', '标签'))

# 镜像同步状态
G_IMAGE_SYNC_STAT = (
    (0, '未同步'),
    (1, '同步成功'),
    (2, '同步失败')
)

# 持续构建状态
G_CI_STATUS = (
    (0, '未构建'),
    (1, '构建成功'),
    (2, '构建失败'),
    (3, '构建中'),
    (4, '作废'),
    (5, '超时未构建')
)

# {0: 未构建, 1: 构建成功, 2: 构建失败, 3: 构建中, 4: 作废}
# 持续部署状态
G_CD_STATUS = (
    (0, '未发布'),
    (1, '成功'),
    (2, '失败'),
    (3, '发布中'),
    (4, '超时'),
    (5, '未知'),
    (11, '分批发布成功'),
    (12, '分批发布失败'),
    (13, '验收不通过'),
    (14, '回退成功')
)

# 部署类型
G_CD_TYPE = (
    (0, '更新应用'),
    (1, '部署新应用'),
    (2, '回退应用'),
    (3, '同版本迭代'),
)
# 镜像删除标记
G_IMAGE_FLAG = ((0, '保留'), (1, '删除'))
# Apollo配置变更标记
G_APOLLO_STATUS = ((0, '无'), (1, '有'))

# Jenkins构建结果标识
JENKINS_STATUS_MAP = {'IN_PROGRESS': 3, 'SUCCESS': 1, 'FAILED': 2, 'ABORTED': 4, 'FAILURE': 2, 'NOT_EXECUTED': 5,
                      'NOT_EXEC_TIMEOUT': 5}
JENKINS_COLOR_MAP = {'SUCCESS': 'green', 'FAILED': 'red', 'ABORTED': 'grey', 'FAILURE': 'red',
                     'NOT_EXECUTED': 'grey', 'NOT_EXEC_TIMEOUT': 'grey', 'IN_PROGRESS': '#cccccc'}

# 应用发布结果标识
ANSIBLE_STATUS = {'success': 1, 'succeeded': 1, 'failure': 2, 'failed': 2, 'change': 1, 'changed': 1, 'skip': 5,
                  'skipped': 5, 'unreachable': 2}
APP_STATUS_MAP = {'success': 'SUCCESS', 'failed': 'FAILED', 0: 'NOT_EXECUTED', 1: 'SUCCESS', 2: 'FAILED', 4: 'ABORTED',
                  5: 'NOT_EXECUTED', 6: 'TIMEOUT'}
APP_COLOR_MAP = {'success': '#67c23a', 'failed': '#f56c6c', 0: '#ccc', 1: '#67c23a', 2: '#f56c6c', 4: '#909399',
                 0: '#e6a23c', 5: '#e6a23c', 6: '#e6a23c'}
DEPLOY_MAP = {True: ['成功', '#67c23a'], False: ['失败', '#f56c6c']}
DEPLOY_NUM_MAP = {1: ['成功', 'green'], 2: ['失败', 'red'],
                  11: ['成功', 'green'], 12: ['失败', 'red']}

# 脱敏字段
SENSITIVE_KEYS = ['password', 'token', 'access',
                  'refresh', 'AUTHORIZATION', 'COOKIE']

# CMDB表字段类型定义
FIELD_TYPE_CHOICES = (
    (0, "string"),
    (1, "textarea"),
    (2, "boolean"),
    (3, "integer"),
    (4, "floating"),
    (5, "Ip"),
    (6, "datetime"),
    (7, "date"),
    (8, "nested"),
    (9, "long"),
)
FIELD_TYPE_CHOICES_DESC = (
    (0, "字符串"),
    (1, "文本"),
    (2, "布尔"),
    (3, "整数"),
    (4, "浮点数"),
    (5, "IP地址"),
    (6, "时间"),
    (7, "日期"),
    (8, "JSON"),
    (9, "长整数")
)
FIELD_TYPE_MAP = {
    0: serializers.CharField,
    1: serializers.CharField,
    2: BooleanField,
    3: serializers.IntegerField,
    4: serializers.FloatField,
    5: serializers.IPAddressField,
    # 5: serializers.CharField,
    6: serializers.DateTimeField,
    7: serializers.DateField,
    8: serializers.JSONField,
    9: serializers.IntegerField,
}


my_normalizer = normalizer('my_normalizer',
                           type="custom",
                           char_filter=[],
                           analyzer='ik_max_word',
                           search_analyzer='ik_smart',
                           filter=["lowercase", "asciifolding"]
                           )
# ElasticSearch字段映射
ES_FIELD_MAP = {
    0: Keyword(normalizer=my_normalizer),
    1: Text(),
    2: Boolean(),
    3: Integer(),
    4: ScaledFloat(scaling_factor=100),
    5: Ip(),
    # 5: Text(),
    6: Date(),
    7: Date(format="yyyy-MM-dd"),
    # 7: Date()
    8: Nested(),
    9: Long(),
}
# 关系型数据库字段映射
ES_MODEL_FIELD_MAP = {
    models.AutoField: Integer(),
    models.BigAutoField: Long(),
    models.BigIntegerField: Long(),
    models.BooleanField: Boolean(),
    models.CharField: Keyword(normalizer=my_normalizer),
    models.DateField: Date(format="yyyy-MM-dd"),
    models.DateTimeField: Date(),
    models.DecimalField: Double(),
    models.EmailField: Text(),
    models.FileField: Text(),
    models.FilePathField: Keyword(),
    models.FloatField: Double(),
    models.ImageField: Text(),
    models.IntegerField: Integer(),
    models.NullBooleanField: BooleanField(),
    models.PositiveIntegerField: Integer(),
    models.PositiveSmallIntegerField: Short(),
    models.SlugField: Keyword(),
    models.SmallIntegerField: Short(),
    models.TextField: Text(),
    models.TimeField: Long(),
    models.URLField: Text(),
    models.UUIDField: Keyword(),
    models.ForeignKey: Integer(),
    models.JSONField: Nested(),
}

ES_TYPE_MAP = {
    0: {"type": "keyword"},
    1: {"type": "long"},
    2: {"type": "double"},
    3: {"type": "date", "format": "yyyy-MM-dd'T'HH:mm:ss"},
    4: {"type": "date", "format": "yyyy-MM-dd"},
    5: {"type": "boolean"},
    6: {"type": "ip"}
}
# CICD消息key
# CICD前缀: {MSG_KEY}{appinfo.env}:{appinfo.app.appid}:{job.build_number}
# 工单前缀: {MSG_KEY}{job.order_id}
# ci消息: {MSG_KEY}:ci:{job.id}
# cd消息: {MSG_KEY}:cd:{job.id}
MSG_KEY = 'cicd:notify::'
# 判断消息是否存在的key
MSG_QUEUE_KEY = 'queue:notify::'  # {MSG_QUEUE_KEY}{MSG_KEY}
# 延时通知key
DELAY_NOTIFY_KEY = 'delay:notify::'  # {DELAY_NOTIFY_KEY}{MSG_KEY}

# CD构建结果key
CI_RESULT_KEY = 'ci:result:'
CD_RESULT_KEY = 'cd:result:'  # {CD_RESULT_KEY}{job.id}
# 部署阶段日志
CD_STAGE_RESULT_KEY = 'cd:result:stage:'
# 最新发布记录
CD_LATEST_KEY = 'cd:deploy:latest::'  # {CD_LATEST_KEY}{appinfo.id}
# WEB构建结果key
CD_WEB_RESULT_KEY = 'cd:deploy:web:job:'  # {CD_WEB_RESULT_EKY}{job.id}
# 构建/部署日志ElasticSearch Index命名
CI_RESULT_INDEX = 'resultbuildjob'
CD_RESULT_INDEX = 'resultdeployjob'

# CI Jenkins回调标记key
# {JENKINS_CALLBACK_KEY}{job.id}
JENKINS_CALLBACK_KEY = 'jenkins_callback_flag::'
# CI构建结果可用镜像key
# {DEPLOY_IMAGE_KEY}{appinfo.app.id or appinfo.app.multiple_ids}
DEPLOY_IMAGE_KEY = 'deployimage:'
# CI最新构建成功key
# {DEPLOY_IMAGE_KEY}:{CI_LATEST_SUCCESS_KEY}
CI_LATEST_SUCCESS_KEY = 'latest:success'
# CI最新构建key
CI_LATEST_KEY = 'ci:deploy:latest::'  # {CI_LATEST_KEY}{appinfo.id}

# 判断部署结果是否已提交查询的key
CD_CHECK_KEY = 'app_deployment_checklist::'  # {CD_CHECK_KEY}{job.image}

# 远程命令/文件传输结果key
REMOTE_RESULT_EKY = 'remote:deploy:job:'  # {REMOTE_RESULT_EKY}{name}

# CMDB资产表索引重建key
REBUILD_INDEX_KEY = 'rebuildIndex::'

# CMDB资产导入key
ASSET_IMPORT_KEY = 'asset::'

# CMDB资产表, 表格宽度
COL_WIDTH_CHOICE = (
    (80, '超短'),
    (180, '默认宽度'),
    (180, '中'),
    (240, '宽'),
    (320, '超宽')
)

# CMDB资产字段分类
CMDB_FIELD_CATEGORY = (
    ('base', '基本信息'),
    ('config', '配置信息'),
    ('business', '业务信息'),
    ('asset', '资产信息'),
    ('uncategory', '未分类'),
    ('cloud', '云资产扩展信息')
)

# CMDB资产外键类型
CMDB_RELATED_TYPE = (
    (0, '无关联'),
    (1, '关系型数据库表关联'),
    (2, 'ElasticSearch索引关联')
)

# 报表类型
DASHBOARD_TYPE = (
    ('cmdb', 'CMDB概览'),
    ('deploy', 'CICD报表'),
    ('dashboard', '首页报表'),
    ('monitor', '监控报表')
)
# 默认报表配置
DASHBOARD_CONFIG = {
    'cmdb': [
        {"key": "区域", "value": "cmdb.product", "type": "rds"},
        {"key": "项目", "value": "cmdb.project", "type": "rds"},
        {"key": "应用", "value": "cmdb.microapp", "type": "rds"},
        {"key": "应用模块", "value": "cmdb.appinfo", "type": "rds"}
    ]
}
# 报表时间格式
DASHBOARD_TIME_FORMAT = {'year_only': '%Y', 'years': '%Y-%m', 'months': '%Y-%m-%d', 'days': '%Y-%m-%d %H:00:00',
                         'hours': '%Y-%m-%d %H:%M:00', 'minutes': '%Y-%m-%d %H:%M:%S'}
DASHBOARD_TIME_FREQNAMES = {'year_only': YEARLY, 'years': MONTHLY, 'months': DAILY, 'days': HOURLY, 'hours': MINUTELY,
                            'minutes': SECONDLY}
# 资产报表时间格式
DASHBOARD_TIME_FORMAT_T = {'years': '%Y', 'months': '%Y-%m', 'days': '%Y-%m-%d', 'hours': "%Y-%m-%d %H:00:00",
                           'minutes': "%Y-%m-%d %H:%M:00", 'seconds': "%Y-%m-%d %H:%M:%S"}
DASHBOARD_TIME_FORMAT_T_ES = {'years': 'yyyy', 'months': 'yyyy-MM', 'days': 'yyyy-MM-dd',
                              'hours': "yyyy-MM-dd HH:00:00", 'minutes': "yyyy-MM-dd HH:mm:00",
                              'seconds': "yyyy-MM-dd HH:mm:ss"}
DASHBOARD_TIME_FREQNAMES_T = {'years': YEARLY, 'months': MONTHLY, 'days': DAILY, 'hours': HOURLY, 'minutes': MINUTELY,
                              'seconds': SECONDLY}
# 数据库模型列表
MODEL_CHOICES = ['cmdb', 'deploy', 'workflow', 'job']
# 时间格式
TIME_FORMAT = {'days': '%Y-%m-%d', 'hours': '%Y-%m-%d %H:00:00', 'minutes': '%Y-%m-%d %H:%M:00',
               'seconds': '%Y-%m-%d %H:%M:%S'}

HARBOR_SECRET = ''
# 开发语言
DEV_LANGUAGE_FILE_MAP = {
    'pipeline': 'Jenkinsfile',
    'dockerfile': 'Dockerfile',
    'template_k8s': 'deployment.yaml'
}
DEV_LANGUAGE_KEY = 'devlanguage:'

# 运算符
OPERATOR_MAP = {'/': 'truediv', '*': 'mul', '**': 'pow',
                '+': 'add', '-': 'sub', '%': 'mod', '//': 'floordiv'}

# 同步AD用户任务KEY
LDAP_SYNC_USER_JOB_CACHE_KEY = 'celery_job:ldap_user_sync'
# 同步飞书组织架构任务key
FEISHU_SYNC_USER_JOB_CACHE_KEY = 'celery_job:feishu_user_sync'

# 数据库工单状态
SQL_WORKFLOW_CHOICES = (
    ("workflow_finish", "完成"),
    ("workflow_abort", "终止"),
    ("workflow_manreviewing", "等待审核"),
    ("workflow_review_pass", "审核通过"),
    ("workflow_timingtask", "定时执行"),
    ("workflow_queuing", "排队中"),
    ("workflow_executing", "执行中"),
    ("workflow_autoreviewwrong", "自动审核不通过"),
    ("workflow_exception", "执行异常"),
)

SQL_QUERY_RESULT_KEY = 'sql:query:'

LOG_GRAPH_INTERVAL = {
    '1s': '1ms',
    '5s': '10ms',
    '10s': '100ms',
    '20s': '400ms',
    '1m': '1s',
    '5m': '5s',
    '10m': '10s',
    '15m': '30s',
    '40m': '1m',
    '3h': '5m'
}
