#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
@Author  : Charles Lai
@Contact : qqing_lai@hotmail.com
@Time    : 2020/5/19 下午5:42
@FileName: tasks.py
@Company : Vision Fund
"""

from __future__ import unicode_literals
from collections import OrderedDict
import logging
import sys
from django.core.cache import cache

from django_q.tasks import async_task, AsyncTask, schedule
from django_q.models import Schedule
from django.db import transaction
from django.utils import timezone

from celery_tasks.celery import app
from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync, sync_to_async
from channels.db import database_sync_to_async
from dbapp.model.model_cmdb import KubernetesDeploy, MicroApp, Project
from dbapp.models import KubernetesCluster, Idc, AppInfo, Environment
from common.utils.GitLabAPI import GitLabAPI
from dbapp.model.model_deploy import BuildJob, DeployJob, PublishApp, PublishOrder, BuildJobResult
from dbapp.model.model_ucenter import UserProfile, SystemConfig, Organization, DataDict
from dbapp.model.model_workflow import Workflow, WorkflowNodeHistory, WorkflowNodeHistoryCallback, WorkflowTemplateRevisionHistory
from workflow.callback_common import callback_work
from kubernetes import client, config, watch
from kubernetes.client import ApiClient
import xlsxwriter
from common.utils.AnsibleCallback import AnsibleApi
from common.utils.JenkinsAPI import GlueJenkins
from common.utils.HarborAPI import HarborAPI
from common.utils.RedisAPI import RedisManage
from common.utils.AesCipher import AesCipher
from common.MailSend import OmsMail
from common.ext_fun import get_datadict, get_datadict, get_redis_data, k8s_cli, set_redis_data, template_svc_generate, \
    get_project_mergerequest
from common.custom_format import convert_xml_to_str_with_pipeline
from common.variables import *

from config import FEISHU_URL, MEDIA_ROOT, SOCIAL_AUTH_FEISHU_KEY, SOCIAL_AUTH_FEISHU_SECRET, SOCIAL_AUTH_GITLAB_API_URL

from ruamel import yaml
import asyncio
import datetime
import json
import time
import pytz
import itertools

logger = logging.getLogger(__name__)

# 机器人类型
ROBOT_CATEGORIES = {}


def clean_image_task(*args):
    """
    调用Harbor API清理镜像
    """
    appinfo_obj = AppInfo.objects.get(id=args[0])
    image = args[1]
    # 获取镜像保留份数
    image_retain = get_datadict('IMAGE_RETAIN', config=1)
    repo = image.split(':')[0]
    # 获取app的k8s集合
    k8s_cluster = appinfo_obj.kubernetes.all()
    for k8s in k8s_cluster:
        try:
            # 获取idc关联的harbor仓库
            harbor = SystemConfig.objects.get(id=k8s.idc.repo)
            # 获取harbor配置
            harbor_config = json.loads(harbor.config)
            logger.info(f'开始清理仓库{harbor.name}镜像{repo}')
            # 调用Harbor api推送
            cli = HarborAPI(url=harbor_config['ip'] + '/api/', username=harbor_config['user'],
                            password=harbor_config['password'])
            # 获取镜像标签
            res = cli.get_tags(repo)
            # 默认保留10份镜像版本
            _retain = (image_retain.get(appinfo_obj.environment.name.split('_')[-1].lower(),
                                        None) if image_retain else 10) or 10
            if res['count'] > _retain:
                # 清理历史版本
                for _t in res['data'][_retain:]:
                    cli.delete_tag(repo, _t['name'])
        except BaseException as e:
            logger.warning(f'清理Harbor[{repo}]标签异常, 原因: {e}')


def docker_image_sync(*args, **kwargs):
    """
    调用Harbor API同步镜像
    """
    # 待发版的app数组
    apps = kwargs['apps']
    for app in apps:
        appinfo_obj = AppInfo.objects.get(id=app['id'])
        namespace = appinfo_obj.namespace
        src_image = app['image']['image']
        _image = src_image.split('/')[-1].split(':')
        image = f"{namespace}/{_image[0]}"
        tag = _image[1]

        # 获取app的k8s集合
        k8s_cluster = appinfo_obj.kubernetes.all()
        for k8s in k8s_cluster:
            # 获取idc关联的harbor仓库
            harbor = SystemConfig.objects.get(id=k8s.idc.repo)
            # 获取harbor配置
            harbor_config = json.loads(harbor.config)
            # 调用Harbor api推送
            cli = HarborAPI(url=harbor_config['ip'], username=harbor_config['user'],
                            password=harbor_config['password'])
            # 检测镜像标签是否存在
            res = cli.fetch_tag(image, tag)
            if res.get('ecode', 500) > 399:
                # 镜像标签不存在
                res = cli.patch_tag(image, src_image, tag)
                if res.get('ecode', 500) > 399:
                    # 打标签异常
                    sync_stat = 1
                else:
                    if isinstance(res['data'], bytes):
                        res['data'] = res['data'].decode('utf-8')
                logger.info(f'{image}:{tag}镜像同步结果: {res}')
            else:
                logger.info(f'{image}:{tag}镜像存在, 不需要同步.')


@app.task
def deploy_notify_cron():
    """
    部署消息通知定时任务
    """
    _keys = [v for k, v in cache.get_many(cache.keys(f'{MSG_KEY}*')).items() if
             isinstance(v, (dict,)) and v.get('msg_key', None)]
    _keys = list(set([i['msg_key'] for i in _keys]))
    for _key in _keys:
        _send = False
        try:
            # 判断是否工单, 工单状态是否完成
            _check_order = _key.split(MSG_KEY)[1].split(':')[0]
            if _check_order.isdigit():
                # 查询工单状态
                if PublishOrder.objects.get(order_id=_check_order).status in [1, 2, 4]:
                    # 标记立即发送
                    _send = True
        except BaseException as e:
            pass
        _delay = 0.1
        delay = cache.get(f"{DELAY_NOTIFY_KEY}{_key}")
        if delay:
            _time_diff = (datetime.datetime.now() - delay['curr_time']).seconds
            # 时间差大于延时则发送消息
            if _time_diff >= delay['delay']:
                _send = True
        if _send:
            _qkeys = cache.keys(f"{_key}:*")
            if _qkeys:
                msg = cache.get(_qkeys[0])
                robot = msg['robot']
                title = msg['title']
                order_id = msg.get('order_id', None)
                deploy_notify_queue.apply_async([_key], {'cron': True, 'order_id': order_id, 'robot': robot,
                                                         'title': title}, countdown=_delay)


def deploy_notify_queue(*args, **kwargs):
    """
    CICD通知队列
    """
    msg_key = args[0]
    appid = kwargs.get('appid', None)
    job_cron = kwargs.get('cron', None)
    title = kwargs['title']
    robot = kwargs['robot']
    order_id = kwargs.pop('order_id', None)
    _keys = sorted(cache.keys(f"{msg_key}:*"), reverse=True)
    msg = cache.get_many(_keys)
    cache.delete_many(_keys)
    if msg:
        async_task(deploy_notify_send, order_id, title, msg, robot)


def deploy_notify_send(order_id, title, msg, robot):
    """
    CICD消息发送
    """
    try:
        _robot = get_redis_data(robot)
        robot_notify = ROBOT_CATEGORIES[_robot.get('type', 'dingtalk')](
            _robot['webhook'], _robot['key'])
        content = '\n---\n'.join([v['msg'] for _, v in msg.items()])
        recv_phone = ','.join(list(
            set([v['recv_phone'] for _, v in msg.items() if v.get('recv_phone', None)])))
        if _robot.get('type', 'dingtalk') == 'feishu':
            # 飞书使用open_id at
            recv_phone = ','.join(list(
                set([v['recv_openid'] for _, v in msg.items() if v.get('recv_openid', None)])))
        if order_id:
            content += f"\n---\n**工单ID: {order_id}**  "
        notify_result = robot_notify.deploy_notify(
            content, recv_phone, title=title)
        if notify_result.get('status', 1) != 0:
            logger.error(f'部署消息[{title}]通知异常, 原因: {notify_result}')
            raise Exception(notify_result)
        logger.info(f'部署消息通知成功: {title} | {recv_phone} | {_robot} | {content}')
    except BaseException as e:
        """
        发送通知异常重试
        """
        logger.error(f'部署消息[{title}]通知异常, 原因: {e}')


def test_notify(receiver, notify_type='mail', robot_name=None, robot_webhook=None, robot_key=None,
                robot_type='dingtalk'):
    ret = None
    if notify_type == 'mail':
        mail_send = OmsMail()
        ret = mail_send.test_notify(receiver)
    if notify_type == 'robot':
        robot_notify = ROBOT_CATEGORIES[robot_type](robot_webhook, robot_key)
        ret = robot_notify.test_notify(receiver, robot_name)

    return ret


def publishorder_notify(self, *args, **kwargs):
    """
    kwargs: [id, creator, apps, title, order_id, created_time, expect_time]
    """
    microapps = MicroApp.objects.filter(
        appinfo__id__in=list(set([i['id'] for i in kwargs['apps']])))
    try:
        team_members_id = []
        [team_members_id.extend(i.team_members.get('op', []))
         for i in microapps]
        team_members = UserProfile.objects.filter(
            id__in=list(set(team_members_id)))
        recv_phone = ','.join(list(set([i.mobile for i in team_members])))
        notify = DataDict.objects.get(key='TICKET_NOTIFY')
        _robot = get_redis_data(notify.value)
        robot_notify = ROBOT_CATEGORIES[_robot['type']](
            _robot['webhook'], _robot['key'])
        msg = f'''你有新的工单待处理!  

标题: {kwargs['title']}  

工单ID: {kwargs['order_id']}  

期望发版时间: {kwargs['expect_time']}  

创建时间: {kwargs['created_time']}

创建人: {kwargs['creator']}  

链接: [{get_redis_data('platform')['url'].strip('/')}/#/deploy/{kwargs['id']}/detail]({get_redis_data('platform')['url'].strip('/')}/#/deploy/{kwargs['id']}/detail)  
    '''
        notify_result = robot_notify.deploy_notify(
            msg, recv_phone, title=kwargs['title'])
        if notify_result.get('status', 1) != 0:
            logger.error(f"工单消息[{kwargs['title']}]通知异常, 原因: {notify_result}")
            raise Exception(notify_result)
        logger.info(
            f"部署消息通知成功: {kwargs['title']} | {recv_phone} | {_robot} | {msg}")
    except BaseException as e:
        logger.error(f"工单消息[{kwargs['title']}通知异常, 原因: {e}")


def k8s_resource_delete(*args, **kwargs):
    k8s_config = kwargs['config']
    resource = kwargs['resource']
    api_version = kwargs['apiversion']
    cluster_id = kwargs['cluster_id']
    k8s = KubernetesCluster.objects.get(id=cluster_id)
    try:
        k8s_config = json.loads(k8s_config)
        cli = k8s_cli(k8s, k8s_config)
        if not cli[0]:
            return None
        cli = cli[1]
    except BaseException as e:
        return None
    ret = []
    if resource == 'deployment':
        ret.append(cli.delete_namespace_deployment(
            kwargs['app_name'], kwargs['namespace'], api_version))
        ret.append(cli.delete_namespace_service(
            kwargs['app_name'], kwargs['namespace'], api_version))
        return ret
    if resource in ['service', 'services']:
        ret.append(cli.delete_namespace_service(
            kwargs['app_name'], kwargs['namespace'], api_version))
        return ret
    if resource == 'configmap':
        ret.append(cli.delete_namespace_configmap(
            kwargs['app_name'], kwargs['namespace'], api_version))
        return ret


@app.task
def k8s_service_create(cluster_id, k8s_config, name, targets, namespace='default', service_type='NodePort'):
    k8s = KubernetesCluster.objects.get(id=cluster_id)
    cli = k8s_cli(k8s, k8s_config)
    if not cli[0]:
        return {'job': '创建Service', 'msg': 'Kubernetes配置异常，请联系运维！'}
    cli = cli[1]
    ret = cli.create_namespace_service(name, targets, namespace, service_type)
    return {'job': '创建Deployment', 'msg': ret}


@app.task
def watch_k8s_update(k8s_config, name, namespace):
    config.kube_config.load_kube_config_from_dict(yaml.safe_load(k8s_config))
    cli = client.AppsV1beta2Api()
    count = 200
    w = watch.Watch()
    for event in w.stream(cli.read_namespaced_deployment(name, namespace), timeout_seconds=10):
        print("Event: %s %s %s" % (
            event['type'],
            event['object'].kind,
            event['object'].metadata.name),
            event
        )
        count -= 1
        if not count:
            w.stop()
    print("Finished pod stream.")


@app.task
def watch_k8s_deployment(*args):
    """
    实时获取前后端应用发布中的日志
    :param args:
    :return:
    """
    channel_name = args[0]
    job_id = args[1]
    app_id = args[2]
    channel_layer = get_channel_layer()
    job = DeployJob.objects.get(id=job_id)

    redis_conn = RedisManage().conn()
    _flag = True
    count = 0
    while _flag:
        app_deploy_stat = cache.get(f'appdeploy:stat:{job.id}')
        msg = cache.get(f'appdeploy:{job.id}')
        if not app_deploy_stat:
            async_to_sync(channel_layer.send)(
                channel_name,
                {
                    "type": "send.message",
                    "message": json.dumps(msg)
                }
            )
            time.sleep(0.5)
            continue

        count += 1
        async_to_sync(channel_layer.send)(
            channel_name,
            {
                "type": "send.message",
                "message": isinstance(msg, str) and msg or json.dumps(msg)
            }
        )
        if count > 5:
            # 部署结束, 发送 devops-done
            time.sleep(3)
            async_to_sync(channel_layer.send)(
                channel_name,
                {
                    "type": "send.message",
                    "message": 'devops-done'
                }
            )
            _flag = False
            if DeployJob.objects.get(id=job_id).status != 3:
                cache.delete(f'appdeploy:{job.id}')
                redis_conn.delete(job.id)


@app.task
def workflow_email_notice(title, msg, receiver):
    # 邮件发送
    mail = OmsMail()
    mail.send_mail(title, msg, receiver, is_html=True)
    logger.debug(f'工单系统 邮件发送 {receiver}')


def workflow_callback(callback_type, workflow_node_history_id, workflow_node_history_callback_id, method, url,
                      headers=None, cookies=None, timeout=30):
    workflow_node_history_obj = WorkflowNodeHistory.objects.get(
        id=workflow_node_history_id)
    workflow_node_history_callback_obj = WorkflowNodeHistoryCallback.objects.get(
        id=workflow_node_history_callback_id)
    try:
        workflow_obj = workflow_node_history_obj.workflow
        first_node_name = workflow_obj.template.nodes[0]['name']
        first_node_form = WorkflowNodeHistory.objects.filter(
            workflow=workflow_obj, node=first_node_name).first().form
        result = callback_work(
            callback_type, method, url,
            template_model_cls=WorkflowTemplateRevisionHistory,
            wid=workflow_node_history_obj.workflow.wid,
            node_name=workflow_node_history_obj.node,
            topic=workflow_node_history_obj.workflow.topic,
            template_id=workflow_node_history_obj.workflow.template.id,
            cur_node_form=workflow_node_history_obj.form,
            first_node_form=first_node_form,
            workflow_node_history_id=workflow_node_history_obj.id,
            headers=headers, cookies=cookies, timeout=timeout
        )
        code = result['response']['code']
        workflow_node_history_callback_obj.response_code = code
        workflow_node_history_callback_obj.response_result = result['response']['data']
    except Exception as e:
        workflow_node_history_callback_obj.response_result = f'workflow_callback 函数发生异常： {e.__class__} {e}'
    workflow_node_history_callback_obj.response_time = timezone.now()
    workflow_node_history_callback_obj.save()
