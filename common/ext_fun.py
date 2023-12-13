#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
@Author : Charles Lai
@Contact : qqing_lai@hotmail.com
@Time : 2020/12/21 上午10:00
@FileName: ext_fun.py
@Blog ：https://imaojia.com
"""
from gitlab.exceptions import GitlabGetError
import copy
from functools import reduce
import operator

from common.utils.ElasticSearchAPI import generate_docu, Search
from common.utils.GitLabAPI import GitLabAPI
from common.utils.HarborAPI import HarborAPI
from common.utils.JenkinsAPI import GlueJenkins
from common.custom_format import convert_xml_to_str_with_pipeline
from common.variables import DASHBOARD_TIME_FORMAT, DASHBOARD_TIME_FORMAT_T, DASHBOARD_TIME_FREQNAMES, \
    DASHBOARD_TIME_FREQNAMES_T, SENSITIVE_KEYS, JENKINS_CALLBACK_KEY, \
    JENKINS_STATUS_MAP, DEV_LANGUAGE_KEY
from dbapp.models import AppInfo, Product, KubernetesCluster, KubernetesDeploy, MicroApp, Project, ProjectConfig, DevLanguage, BuildJob, UserProfile, SystemConfig, Role, Permission, Menu, DataDict

from django.conf import settings
from django.core.cache import cache
from django.utils import timezone
from django.db.models import Q
from social_django.utils import load_strategy
from rest_framework.utils.serializer_helpers import ReturnDict

from config import SOCIAL_AUTH_GITLAB_API_URL, GITLAB_ADMIN_TOKEN

from common.utils.K8sAPI import K8sAPI

from urllib.parse import urlparse, quote_plus
from dateutil.relativedelta import relativedelta
from dateutil.rrule import rrule
from ruamel import yaml
from datetime import datetime, timedelta
import re
import time
import pytz
import os
import json
import requests
import math
import shortuuid
import logging

logger = logging.getLogger('drf')


class ThirdPartyUser(object):

    def get_user(self):
        user = UserProfile.objects.get_or_create(username='thirdparty')[0]
        self.set_permission(user, self.get_role())
        return user

    def get_role(self):
        return Role.objects.get_or_create(name='thirdparty')[0]

    def get_perm(self):
        return Permission.objects.get_or_create(name='Jenkins回调', method='jenkins_callback')[0]

    def set_permission(self, user, role):
        role.permissions.set([self.get_perm().id])
        user.roles.set([role.id])


def set_redis_data(name, config):
    cache.set(f"system:{name}", config, None)


def get_redis_data(name):
    ret = cache.get(f"system:{name}")
    if not ret:
        try:
            if name == 'cicd-harbor':
                qs = SystemConfig.objects.filter(type=name)[0]
            else:
                qs = SystemConfig.objects.get(name=name)
        except BaseException as e:
            return None
        ret = json.loads(qs.config)
        set_redis_data(name, ret)

    return ret


def get_datadict(name, config=0, default_value=None):
    """
    从数据字典获取数据
    """
    try:
        qs = DataDict.objects.get(key=name)
    except BaseException as e:
        return default_value
    if config:
        ret = json.loads(qs.extra)
    else:
        ret = {'id': qs.id, 'key': qs.key,
               'value': qs.value, 'desc': qs.desc}
    return ret


def check_pods(cluster_id, k8s_config, namespace, **kwargs):
    k8s = KubernetesCluster.objects.get(id=cluster_id)
    cli = k8s_cli(k8s, k8s_config)
    if not cli:
        return False
    count = 3
    while count:
        ret2 = cli.get_pods(namespace, **kwargs)
        count -= 1
        if len(ret2['items']) > 0:
            return True
        else:
            check_pods(k8s_config, namespace, **kwargs)
    return False


def template_svc_generate(appinfo_obj):
    """
    生成Kubernetes Svc Yaml

    ### 格式：
        {
            "apiVersion": "v1",
            "kind": "Service",
            "metadata": {
                "name": "appname",
                "namespace": "env-product",
                "labels": {
                    "app": "appname"
                }
            },
            "spec": {
                "ports": [{
                    "port": 8080,
                    "targetPort": 8080,
                    "protocol": "TCP",
                    "name": "http"
                }],
                "selector": {
                    "app": "appname"
                }
            }
        }
    """
    svc_temp = DataDict.objects.filter(key='yaml.svc')
    if svc_temp.exists():
        svc_temp = json.loads(svc_temp.first().extra)
        if appinfo_obj.environment.name in svc_temp:
            svc_temp = svc_temp[appinfo_obj.environment.name]
            namespace = appinfo_obj.namespace
            svc_temp['metadata']['name'] = appinfo_obj.app.name
            svc_temp['metadata']['namespace'] = namespace
            svc_temp['metadata']['labels'] = {'app': appinfo_obj.app.name}

            labels = []
            labels.extend([{'name': 'app', 'value': appinfo_obj.app.name}])

            svc_temp['spec']['selector'] = {
                i['name']: i['value'] for i in labels}
            return True, svc_temp
    return False, None


def harbor_cli(namespace, **filters):
    try:
        harbor = SystemConfig.objects.filter(**filters).first()
        # 获取harbor配置
        harbor_config = json.loads(harbor.config)
    except BaseException as e:
        logger.exception(f'创建任务失败, 原因: 获取harbor仓库异常, {e}')
        return False, f"获取harbor仓库异常：{e}"
    # 构建前创建harbor项目
    cli = HarborAPI(url=harbor_config['url'], username=harbor_config['user'],
                    password=harbor_config['password'])
    try:
        cli.create_project(
            namespace, public=harbor_config.get('public', False))
    except BaseException as e:
        pass
    return True, harbor_config


def k8s_cli(k8s, k8s_config):
    try:
        if k8s_config['type'] == 'basic':
            # basic auth or token auth
            k8s_config.pop('config', None)
            k8s_config.pop('type', None)
            cli = K8sAPI(**k8s_config)
        else:
            eks = None
            eks_token = None
            k8s_config = yaml.safe_load(k8s_config['config'])
            if k8s.idc.type == 1 and k8s.idc.supplier.split('.')[-1] == 'aws':
                return False, 'not support.'
            cli = K8sAPI(k8s_config=k8s_config, api_key=eks_token, eks=eks)
        return True, cli
    except BaseException as e:
        return False, str(e)


def template_generate(appinfo_obj: AppInfo, image=None, partial_deploy_replicas: int = 0):
    """
    生成Kubernetes Deployment Yaml
    """

    def health_lifecycle_generate(item, enable=True):
        _c = {}
        for i in template[item]['data']:
            _x = {}
            if i.get('enable', enable):
                for j in i['items']:
                    if '__' in j['name']:
                        _t = j['name'].split('__')
                        _value = j['value']
                        if j['name'] == 'exec__command':
                            _value = ["sh", "-c", j['value']]
                        if _x.get(_t[0], None):
                            _x[_t[0]][_t[1]] = _value
                        else:
                            _x[_t[0]] = {_t[1]: _value}
                    else:
                        _x[j['name']] = j['value']
                _c[i['name']] = _x
        return _c

    def container_generate(container_data):
        containers = []
        for i in container_data:
            if i.get('enable', None):
                container = get_datadict(i['key'], config=1)
                if not container:
                    container = i['extra']
                containers.append(
                    container)
        return containers
    language_obj = DevLanguage.objects.get(name=appinfo_obj.app.language)
    project_config = ProjectConfig.objects.filter(project_id=appinfo_obj.app.project.id,
                                                  environment_id=appinfo_obj.environment.id)
    namespace = appinfo_obj.namespace
    harbor_config = get_redis_data('cicd-harbor')
    harbor_url = harbor_config['url'].split('://')[1]
    image = f"{harbor_url}/{image}"

    template = {}
    # 模板优先级
    # 应用模块 -> 应用 -> 项目 -> 环境
    if project_config.first():
        project_template = project_config.first().template
        for k, v in project_template.items():
            if v and isinstance(v, (dict,)):
                if v.get('custom', False) is False:
                    if appinfo_obj.environment.template.get(k, None):
                        template[k] = appinfo_obj.environment.template[k]
                else:
                    if project_template.get(k, None):
                        template[k] = project_template[k]

    microapp_template = appinfo_obj.app.template
    for k, v in microapp_template.items():
        if '_on' in k and v:
            _k = k.rstrip('_on')
            if microapp_template.get(_k, None):
                template[_k] = microapp_template[_k]
    use_host_network = False
    if appinfo_obj.template.get('userHostNetwork', 0):
        use_host_network = True
    for k, v in appinfo_obj.template.items():
        if v and isinstance(v, (dict,)):
            if v.get('custom', False) and appinfo_obj.template.get(k, None):
                template[k] = appinfo_obj.template[k]

    yaml_template = {'kind': 'Deployment', 'metadata': {}, 'spec':
                     {'strategy': {}, 'template': {'metadata': {}, 'spec':
                                                   {'containers': [{'ports': [{'containerPort': 8080}], 'resources': []}],
                                                    'imagePullSecrets': [{'name': 'loginharbor'}],
                                                    'terminationGracePeriodSeconds': 120}
                                                   }
                      }
                     }

    try:
        tz = appinfo_obj.app.project.product.region.extra['timezone']
    except BaseException as e:
        tz = 'Asia/Shanghai'
    try:
        if template.get('strategy', None):
            for i in template['strategy']['data']:
                if i['key'] in ['maxSurge', 'maxUnavailable']:
                    if yaml_template['spec']['strategy'].get('rollingUpdate', None) is None:
                        yaml_template['spec']['strategy']['rollingUpdate'] = {}
                    yaml_template['spec']['strategy']['rollingUpdate'][i['key']
                                                                       ] = f"{i['value']}%"
                else:
                    yaml_template['spec'][i['key']] = i['value']
        _d = {}
        for i in template['resources']['data']:
            _t = i['key'].split('_')
            if _d.get(_t[0], None):
                _d[_t[0]][_t[1]] = f"{i['value']}{i['slot']}"
            else:
                _d[_t[0]] = {_t[1]: f"{i['value']}{i['slot']}"}
        yaml_template['spec']['template']['spec']['containers'][0]['resources'] = _d

        yaml_template['metadata']['name'] = appinfo_obj.app.name
        yaml_template['metadata']['namespace'] = namespace
        yaml_template['spec']['template']['spec']['containers'][0]['name'] = appinfo_obj.app.name
        yaml_template['spec']['template']['spec']['containers'][0]['image'] = image
        command = appinfo_obj.app.template.get(
            'command', None) or language_obj.labels.get('command', None)
        if command:
            if command.startswith('./'):
                yaml_template['spec']['template']['spec']['containers'][0]['command'] = [
                    command]
            else:
                yaml_template['spec']['template']['spec']['containers'][0]['command'] = [
                    'sh', '-c', command]

        # 优先级: 应用模块>应用>预设>开发语言
        labels = template['label']['data']
        labels.extend([{'name': 'app', 'value': appinfo_obj.app.name}])
        yaml_template['spec']['template']['metadata']['labels'] = {
            i['name']: i['value'] for i in labels}
        yaml_template['spec']['template']['metadata']['labels'][
            'status-app-name-for-ops-platform'] = appinfo_obj.app.name
        yaml_template['spec']['selector'] = {
            'matchLabels': {i['name']: i['value'] for i in labels}}

        selectors = template['selector']['data']
        yaml_template['spec']['template']['spec']['nodeSelector'] = {
            i['name']: i['value'] for i in selectors}

        if 'annotations' not in yaml_template['spec']['template']['metadata']:
            yaml_template['spec']['template']['metadata']['annotations'] = {}

        for i in template['prometheus']['data']:
            yaml_template['spec']['template']['metadata'][
                'annotations'][f'prometheus.io/{i["name"]}'] = i['value']
        if 'prometheus.io/path' in yaml_template['spec']['template']['metadata']['annotations']:
            yaml_template['spec']['template']['metadata']['annotations'][
                'prometheus.io/app_product'] = appinfo_obj.app.project.product.name
            yaml_template['spec']['template']['metadata']['annotations'][
                'prometheus.io/app_env'] = appinfo_obj.environment.name
            yaml_template['spec']['template']['metadata']['annotations'][
                'prometheus.io/app_project'] = appinfo_obj.app.project.name

        # 环境变量
        envs = [{'name': 'TZ', 'value': tz}]
        envs.extend(template['env']['data'])
        envs.extend([
            {'name': '_RESTART', 'value': datetime.now().strftime(
                '%Y%m%d%H%M%S')},  # _RESTART变量用于强制更新deployment
            {'name': 'PRODUCT_NAME', 'value': appinfo_obj.app.project.product.name},
            {'name': 'PROJECT_NAME', 'value': appinfo_obj.app.project.name},
            {'name': 'APPNAME', 'value': appinfo_obj.app.name},
            {'name': 'APPID', 'value': appinfo_obj.app.appid},
            {'name': 'ENV', 'value': appinfo_obj.environment.name},
            {'name': 'POD_NAMESPACE', 'value': namespace}
        ])
        envs = list({i['name']: i for i in envs}.values())
        for i in envs:
            try:
                env_value = i.get('value', None)
                cmname = i.pop('cmname', None)
                cmkey = i.pop('cmkey', None)
                if env_value:
                    env_value = env_value.lstrip('"').rstrip(
                        '"').lstrip("'").rstrip("'")
                i.pop('value', None)
                i['name'] = i['name'].lstrip('"').rstrip(
                    '"').lstrip("'").rstrip("'")
                if i.get('valueFrom', None) == 'configMapKeyRef':
                    i['valueFrom'] = {'configMapKeyRef': {
                        'name': cmname, 'key': cmkey}}
                else:
                    i['value'] = env_value
                    i['valueFrom'] = None
            except BaseException as e:
                pass
        yaml_template['spec']['template']['spec']['containers'][0]['env'] = envs

        if template.get('health', False):
            _d = health_lifecycle_generate('health', True)
            for k, v in _d.items():
                yaml_template['spec']['template']['spec']['containers'][0][k] = v
        if template.get('lifecycle', False):
            yaml_template['spec']['template']['spec']['containers'][0]['lifecycle'] = {
            }
            _d = health_lifecycle_generate('lifecycle', False)
            for k, v in _d.items():
                yaml_template['spec']['template']['spec']['containers'][0]['lifecycle'][k] = v

        _vo_mount = [{'mountPath': '/data/logs',
                      'name': 'logs', 'readOnly': False}]
        _volumes = [{'name': 'logs', 'type': 'Directory', 'hostPath': {
            'path': f'/data/{appinfo_obj.environment.name}-applogs/{appinfo_obj.app.project.name}/'}}]
        if template.get('storage', None):
            for k, v in template['storage']['data'].items():
                for i in v:
                    _x = {}
                    for m, n in i.items():
                        if isinstance(n, (str,)):
                            n = n.replace('${APPNAME}', appinfo_obj.app.name)
                        if '_' in m:
                            _t = m.split('_')
                            if _x.get(_t[0], None):
                                _x[_t[0]][_t[1]] = n
                            else:
                                _x[_t[0]] = {_t[1]: n}
                        else:
                            _x[m] = n
                    _t = {'mountPath': _x['mount'], 'name': _x['name'],
                          'readOnly': True if _x.get('mode', None) == 'ReadOnly' else False}
                    if _x.get('file', None):
                        _t['subPath'] = _x['configMap']['items'][0]['key']
                    _vo_mount.append(_t)
                    _mode = _x.pop('mode', None)
                    _x.pop('file', None)
                    _x.pop('mount', None)
                    if _x.get('configMap', None):
                        _x['configMap']['defaultMode'] = 0o600 if _mode == 'ReadOnly' else 0o755
                    _volumes.append(_x)
        yaml_template['spec']['template']['spec']['containers'][0]['volumeMounts'] = _vo_mount
        yaml_template['spec']['template']['spec']['volumes'] = _volumes
        if use_host_network:
            yaml_template['spec']['template']['spec']['hostNetwork'] = True
        partial_deploy_yaml_template = None

    except BaseException as e:
        logger.exception(f'generate yaml err {e.__class__} {e}')
        return {'ecode': 500, 'message': str(e)}

    # 多容器处理
    if appinfo_obj.template.get('containers_custom', None):
        containers = container_generate(
            appinfo_obj.template.get('containers', []))
    else:
        containers = container_generate(
            project_config.first().template.get('containers', []))
    yaml_template['spec']['template']['spec']['containers'].extend(containers)
    ret = {'ecode': 200, 'image': image, 'yaml': yaml_template}

    if partial_deploy_yaml_template:
        ret['partial_deploy_yaml'] = partial_deploy_yaml_template
    return ret


def get_members(obj):
    team_members = [j for i in obj.team_members.values() for j in i]
    return list(set(team_members))


def get_permission_from_role(request):
    try:
        perms = request.user.roles.values(
            'permissions__method',
        ).distinct()
        return [p['permissions__method'] for p in perms]
    except AttributeError:
        return []


def get_headers(request=None):
    """
        Function:       get_headers(self, request)
        Description:    To get all the headers from request
    """
    regex = re.compile('^HTTP_')
    return dict((regex.sub('', header), value) for (header, value)
                in request.META.items() if header.startswith('HTTP_'))


def mask_sensitive_data(data):
    """
    Hides sensitive keys specified in sensitive_keys settings.
    Loops recursively over nested dictionaries.
    """

    if hasattr(settings, 'DRF_API_LOGGER_EXCLUDE_KEYS'):
        if type(settings.DRF_API_LOGGER_EXCLUDE_KEYS) in (list, tuple):
            SENSITIVE_KEYS.extend(settings.DRF_API_LOGGER_EXCLUDE_KEYS)

    if type(data) != dict and type(data) != ReturnDict:
        try:
            data = json.loads(data)
        except BaseException as e:
            return data

    for key, value in data.items():
        if key in SENSITIVE_KEYS:
            data[key] = "***FILTERED***"

        if type(value) == dict:
            data[key] = mask_sensitive_data(data[key])

    return data


def time_convert(target_time):
    """
    时间转字符串
    """
    return target_time.astimezone(pytz.timezone('Asia/Shanghai')).strftime('%Y-%m-%d %H:%M:%S+08:00')


def time_comp(target_time, **kwargs):
    """
    时间比较/统一使用utc时间对比
    target_time: 目标时间
    kwargs: 额外参数, 时间差 如{hours: 1}, {minutes: 1}, {seconds: 1}, 数值不取负数
    """
    ctime = timezone.now()
    if kwargs:
        # 两个时间是否在期望时间差范围
        if target_time > ctime:
            return target_time - ctime <= timedelta(**kwargs)
        else:
            return ctime - target_time <= timedelta(**kwargs)
    # 判断两个时间是否相等
    return ctime == target_time


def timeline_generate(time_range, format_type='dashboard'):
    """
    根据起始时间生成时间线

    : params format_type: 默认为dashboard, 用于概览报表粗略显示, 其它用于监控类的展示则使用更细粒度的格式
    """
    TIME_FREQNAMES = DASHBOARD_TIME_FREQNAMES
    TIME_FORMAT = DASHBOARD_TIME_FORMAT
    if format_type == 'cmdb':
        TIME_FREQNAMES = DASHBOARD_TIME_FREQNAMES_T
        TIME_FORMAT = DASHBOARD_TIME_FORMAT_T
    start_time = time_range['start_time']
    end_time = time_range['end_time']
    time_line = rrule(
        freq=TIME_FREQNAMES[time_range['name']], dtstart=start_time, until=end_time)
    return [i.strftime(TIME_FORMAT[time_range['name']]) for i in time_line]


def time_period(time_range='6-months', type_range='static', time_zone='Asia/Shanghai', name=None):
    """
    根据时间范围生成起止时间
    """
    start_time = None
    end_time = timezone.now().astimezone(pytz.timezone(time_zone))
    if type_range == 'dynamic' and name is None:
        start_time = datetime.strptime(time_range[0], '%Y-%m-%d %H:%M:%S')
        end_time = datetime.strptime(time_range[1], '%Y-%m-%d %H:%M:%S')
        if start_time > end_time:
            start_time, end_time = end_time, start_time
        if (end_time - start_time).days >= 60:
            name = 'months'
        elif (end_time - start_time).days >= 2:
            name = 'days'
        elif (end_time - start_time).days >= 1 or (end_time - start_time).seconds > 60 * 60:
            name = 'hours'
        else:
            name = 'minutes'
        return {'name': name, 'start_time': start_time, 'end_time': end_time}

    if type_range == 'static':
        _time = time_range.split('-')
        if _time[-1] == 'week':
            start_time = end_time - relativedelta(days=end_time.weekday(), hours=end_time.hour, minutes=end_time.minute,
                                                  seconds=end_time.second,
                                                  microseconds=end_time.microsecond)
            return {'name': 'days', 'start_time': start_time, 'end_time': end_time}
        if _time[-1] == 'lastweek':
            start_time = end_time - relativedelta(days=end_time.weekday() + 7, hours=end_time.hour,
                                                  minutes=end_time.minute, seconds=end_time.second,
                                                  microseconds=end_time.microsecond)
            end_time = end_time - relativedelta(days=end_time.weekday(), hours=end_time.hour, minutes=end_time.minute,
                                                seconds=end_time.second, microseconds=end_time.microsecond)
            return {'name': 'days', 'start_time': start_time, 'end_time': end_time}
        if _time[-1] in ['today', 'yesterday']:
            start_time = end_time - relativedelta(hours=end_time.hour, minutes=end_time.minute, seconds=end_time.second,
                                                  microseconds=end_time.microsecond)
            if _time[-1] == 'yesterday':
                end_time = start_time
                start_time = end_time - relativedelta(days=1)
            return {'name': 'hours', 'start_time': start_time, 'end_time': end_time}
        name = _time[1]
        if name is None:
            if _time[1] in ['years', 'months']:
                name = 'months'
            if _time[1] == 'months' and int(_time[0]) < 2:
                name = 'days'
            if _time[1] == 'days' and int(_time[0]) < 2:
                name = 'hours'
        start_time = end_time + relativedelta(**{_time[1]: -int(_time[0])})
        return {'name': name, 'start_time': start_time, 'end_time': end_time}


def extend_jenkins(data, env):
    jenkins = get_redis_data('cicd-jenkins')
    app = AppInfo.objects.filter(id=data['id'])[0]
    category = DataDict.objects.get(key=app.app.category)
    job_name = app.jenkins_jobname
    jenkins_cli = GlueJenkins(jenkins.get('url', 'http://localhost'), username=jenkins.get('user', 'admin'),
                              password=jenkins.get('password', None))
    try:
        view_xml_config = f'''<?xml version="1.0" encoding="UTF-8"?>
<hudson.model.ListView>
<name>{app.app.project.alias}{env.alias}</name>
<filterExecutors>false</filterExecutors>
<filterQueue>false</filterQueue>
<properties class="hudson.model.View$PropertyList"/>
<jobNames>
<comparator class="hudson.util.CaseInsensitiveComparator"/>
</jobNames>
<jobFilters/>
<columns>
<hudson.views.StatusColumn/>
<hudson.views.WeatherColumn/>
<hudson.views.JobColumn/>
<jenkins.branch.DescriptionColumn/>
<hudson.views.LastSuccessColumn/>
<hudson.views.LastFailureColumn/>
<hudson.views.LastDurationColumn/>
<hudson.views.BuildButtonColumn/>
</columns>
<includeRegex>{env.name.lower()}-.*-{app.app.project.name.lower()}-.*</includeRegex>
</hudson.model.ListView>'''
        jenkins_cli.create_view(
            f'{app.app.project.alias}{env.alias}', view_xml_config)
    except BaseException as e:
        pass
    try:
        config_xml = convert_xml_to_str_with_pipeline(jenkins['xml'], jenkins['pipeline']['http_url_to_repo'],
                                                      jenkins['gitlab_credit'],
                                                      app.app.alias,
                                                      f'{app.app.language}/Jenkinsfile')
        if not jenkins_cli.job_exists(job_name):
            jenkins_cli.create_job(name=job_name, config_xml=config_xml)
        else:
            jenkins_cli.reconfig_job(name=job_name, config_xml=config_xml)
    except Exception as e:
        logger.error(f"创建Jenkins JOB: {job_name}  失败  ERROR: {e}")


def get_celery_tasks():
    """
    获取celery任务
    """
    from celery import current_app
    current_app.loader.import_default_modules()
    tasks = list(
        sorted(name for name in current_app.tasks if not name.startswith('celery.')))
    return tasks


def is_chinese(string):
    """
    检查整个字符串是否包含中文
    :param string: 需要检查的字符串
    :return: bool
    """
    for ch in string:
        if u'\u4e00' <= ch <= u'\u9fff':
            return True
    return False


def get_word_list(string):
    """
    切割字符串, 中文/-切割成单个字, 其它则切割成单个词
    """
    res = re.compile(r"([\u4e00-\u9fa5\-])")
    return [i for i in res.split(string.lower()) if len(i.strip()) > 0 and i != '-']


def devlanguage_template_manage(instance, filename, user=None, content=None, action='retrieve'):
    jenkins = get_redis_data('cicd-jenkins')
    ok, cli = gitlab_cli(admin=True)
    if not ok:
        return False, cli
    project_id = jenkins['pipeline'].get('id', None)
    if not project_id:
        return False, '获取流水线失败，请检查Jenkins配置.'
    project = cli.get_project(project_id)
    items = project.repository_tree(path=instance.name)
    try:
        if action == 'update':
            if filename in [i['name'] for i in items]:
                # 文件已存在则更新
                f = project.files.get(
                    f"{instance.name}/{filename}", ref='master')
                f.content = content
                f.save(
                    branch='master', commit_message=f'Update {instance.name} {filename} by {user.username}')
            else:
                # 文件不存在则创建
                logger.info(f'{instance.name}/{filename}文件不存在则创建')
                project.files.create({'file_path': f"{instance.name}/{filename}",
                                      'branch': 'master',
                                      'content': content,
                                      'author_email': user.email,
                                      'author_name': user.username,
                                      'commit_message': f'Create {instance.name} {filename} by {user.username}'})
        content = project.files.raw(
            f"{instance.name}/{filename}", ref='master')
        return True, content
    except GitlabGetError as e:
        logger.info(f'获取异常，{e}')
        if e.response_code == 404:
            logger.info(f'{instance.name}/{filename}文件不存在')
            return True, ''
    except BaseException as e:
        logger.error(f'GitLab开发语言模板异常, 原因: {e}')
        return False, f'GitLab开发语言模板异常, 原因: {e}'


def snake_case(x):
    """
    驼峰转下划线
    """

    term_exclude = ['OS', 'GPU', 'DB', 'IA', 'IP',
                    'RR', 'TTL', 'SLB', 'CPU', 'MEMORY', 'QPS']
    for i in term_exclude:
        x = x.replace(i, i.lower())
    return re.sub(r'(?P<key>[A-Z])', r'_\g<key>', x).lower().strip('_')


def node_filter(node_id, data):
    """
    查找节点

    :params: node_id int 节点ID
    :params: data list 节点数组
    """
    for i in data:
        if i['id'] == node_id:
            print('get node', i)
            return i
        else:
            if i.get('children', None):
                node = node_filter(node_id, i['children'])
                if isinstance(node, (dict,)):
                    return node


def get_time_range(request):
    """
    获取时间轴
    """
    type_range = request.query_params.get('range_type', 'static')
    if type_range == 'static':
        time_range = request.query_params.get('range', '6-months')
    else:
        time_range = request.query_params.getlist('range[]', None)
    if not time_range:
        time_range = '6-months'
    period = time_period(time_range, type_range)
    time_line = timeline_generate(period, format_type='cmdb')
    # 时间刻度, 以小时为刻度则删除年份
    time_line_x = [i.split(' ')[-1]
                   for i in time_line] if period['name'] == 'hours' else time_line
    return period, time_line, time_line_x


def compare_dict(data, old_data):
    different_list = []
    for k1 in data:
        if k1 == 'update_time':
            continue
        v1 = data.get(k1)
        v2 = old_data.get(k1)
        if v1 != v2:
            different_list.append({
                'key': k1,
                'new_value': v1,
                'old_value': v2
            })

    return different_list


def get_project_mergerequest(project: Project, cli: GitLabAPI, **params):
    """
    获取项目下所有应用的合并请求
    """
    mrdata = []
    git_project = [app.repo['id']
                   for app in project.microapp_set.all() if app.repo.get('id')]
    for project_id in set(git_project):
        try:
            git_project = cli.get_project(project_id)
            ok, data = cli.list_mrs(project=git_project, **params)
            if ok is False:
                continue
            mrdata.extend([i.attributes for i in data])
        except BaseException as e:
            logger.error(f'获取应用合并请求异常，原因：{e}')
    return mrdata


def gitlab_cli(user=None, admin=False, superadmin=False, merge=False):
    """
    获取GitlabAPI
    :param merge: 用于分支合并，管理员统一用配置文件里的token
    """
    try:
        payload = {'token': GITLAB_ADMIN_TOKEN, 'oauth': False}
        cli = GitLabAPI(SOCIAL_AUTH_GITLAB_API_URL, **payload)
        return True, cli
    except BaseException as e:
        logger.warning(f'获取GitlabAPI异常，原因：{e}')
        return False, f'获取GitlabAPI异常，原因：{e}'


def get_deploy_image_list(app_id, appinfo_id=None, module=None, force=0):
    # 可选发布镜像
    # 获取关联应用ID
    app = MicroApp.objects.get(id=app_id)
    appinfo_obj = AppInfo.objects.get(id=appinfo_id)
    if app.multiple_app:
        appinfo_objs = AppInfo.objects.filter(
            app_id__in=app.multiple_ids, environment=appinfo_obj.environment)
    else:
        appinfo_objs = AppInfo.objects.filter(
            app_id=app_id, environment=appinfo_obj.environment)
    allow_branch = appinfo_obj.allow_cd_branch or appinfo_obj.environment.allow_cd_branch
    if not allow_branch:
        logger.info(f"应用{appinfo_obj.app.appid}无可用镜像, 原因: 允许发布分支为空!")
        return None
    rds_branch_conditions = [Q(commit_tag__name__icontains=i.replace('*', ''))
                             for i in set(allow_branch)]
    queryset = BuildJob.objects.filter(appinfo_id__in=list(
        set([i.id for i in appinfo_objs])), status=1)
    if '*' not in allow_branch:
        queryset = BuildJob.objects.filter(appinfo_id__in=list(set([i.id for i in appinfo_objs])), status=1).filter(
            reduce(operator.or_, rds_branch_conditions))
    return queryset
