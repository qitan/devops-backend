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

from django.db import transaction
from django.utils import timezone

from celery_tasks.celery import app
from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync, sync_to_async
from channels.db import database_sync_to_async
from dbapp.models import KubernetesDeploy, MicroApp, Project
from dbapp.models import KubernetesCluster, Idc, AppInfo, Environment
from common.utils.GitLabAPI import GitLabAPI
from dbapp.models import BuildJob, DeployJob, PublishApp, PublishOrder, BuildJobResult
from dbapp.models import UserProfile, SystemConfig, Organization, DataDict
from dbapp.models import WorkflowNodeHistory, WorkflowNodeHistoryCallback, WorkflowTemplateRevisionHistory
from qtasks.tasks_build import JenkinsBuild
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
from common.ext_fun import get_datadict, get_redis_data, k8s_cli, set_redis_data, template_svc_generate
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
def tail_k8s_log(channel_name, pod_name, namespace, cluster_id, lines=None):
    if not lines:
        lines = 100
    channel_layer = get_channel_layer()
    k8s = KubernetesCluster.objects.get(id=cluster_id)
    k8s_config = json.loads(k8s.config)
    cli2 = k8s_cli(k8s, k8s_config)
    if not cli2[0]:
        async_to_sync(channel_layer.send)(
            channel_name,
            {
                "type": "send.message",
                "pod": pod_name,
                "message": 'Kubernetes配置异常，请联系运维！'
            }
        )
        async_to_sync(channel_layer.send)(
            channel_name,
            {
                "type": "send.message",
                "pod": pod_name,
                "message": 'devops-done'
            }
        )
        return
    cli2 = cli2[1]
    w = watch.Watch()
    count = 0
    for event in w.stream(cli2.get_client().read_namespaced_pod_log, pod_name, namespace, tail_lines=lines):
        count += 1
        if event:
            async_to_sync(channel_layer.send)(
                channel_name,
                {
                    "type": "send.message",
                    "pod": pod_name,
                    "message": event
                }
            )
        time.sleep(0.05)

        if count > 3600:
            async_to_sync(channel_layer.send)(
                channel_name,
                {
                    "type": "send.message",
                    "pod": pod_name,
                    "message": 'devops-done'
                }
            )
            w.stop()
            break

    print("Finished pod stream.")


@app.task
def watch_k8s_pod(channel_name, cluster_id, namespace, service):
    channel_layer = get_channel_layer()
    k8s = KubernetesCluster.objects.get(id=cluster_id)
    k8s_config = json.loads(k8s.config)
    cli2 = k8s_cli(k8s, k8s_config)
    if not cli2[0]:
        async_to_sync(channel_layer.send)(
            channel_name,
            {
                "type": "send.message",
                "message": 'Kubernetes配置异常，请联系运维！'
            }
        )
        async_to_sync(channel_layer.send)(
            channel_name,
            {
                "type": "send.message",
                "message": 'devops-done'
            }
        )
        return
    cli2 = cli2[1]
    w = watch.Watch()
    selectd = {"label_selector": f"app={service}"}
    _flag = False
    count = 0
    for event in w.stream(cli2.get_client().list_namespaced_pod, namespace, **selectd):
        count += 1
        if event:
            rs = ApiClient().sanitize_for_serialization(event)
            async_to_sync(channel_layer.send)(
                channel_name,
                {
                    "type": "send.message",
                    "message": json.dumps(rs)
                }
            )
        time.sleep(0.05)
        #
        if count > 3600:
            async_to_sync(channel_layer.send)(
                channel_name,
                {
                    "type": "send.message",
                    "message": 'devops-done'
                }
            )
            w.stop()
            break
    print("Finished pod stream.")


@app.task
def jenkins_log_stage(channel_name, job_id, appinfo_id=0, job_type='app'):
    try:
        channel_layer = get_channel_layer()
        JENKINS_CONFIG = get_redis_data('cicd-jenkins')
        jbuild = JenkinsBuild(JENKINS_CONFIG['url'], username=JENKINS_CONFIG['user'],
                              password=JENKINS_CONFIG['password'], job_id=job_id, appinfo_id=appinfo_id, job_type=job_type)
        count = 0
        _flag = True
        while _flag:
            time.sleep(0.5)
            count += 1
            try:
                job_name, job, _ = jbuild.job_info()
                ok, flow_json = jbuild.log_stage()
                if ok:
                    _flag = False
                message = flow_json

                if count > 600 and flow_json['status'] == 'NOT_EXECUTED':
                    message = {'status': 'NOT_EXEC_TIMEOUT',
                               'stages': [{'logs': '构建超时，请联系运维排查！'}]}
                    _flag = False
                if count > 900 and flow_json['status'] == 'IN_PROGRESS':
                    message = {'status': 'NOT_EXEC_TIMEOUT',
                               'stages': [{'logs': '构建检测超时，请联系运维排查！'}]}
                    _flag = False

                async_to_sync(channel_layer.send)(
                    channel_name,
                    {
                        "type": "send.message",
                        "message": message
                    }
                )
                if count > 600 or _flag is False:
                    async_to_sync(channel_layer.send)(
                        channel_name,
                        {
                            "type": "send.message",
                            "message": 'devops-done'
                        }
                    )
                    break
            except BaseException as e:
                continue
    except BaseException as e:
        pass


@app.task
def jenkins_log_console(*arg, **kwargs):
    channel_name = kwargs['channel_name']
    job_id = kwargs['job_id']
    appinfo_id = kwargs.get('appinfo_id', 0)
    job_type = kwargs.get('job_type', 'app')

    channel_layer = get_channel_layer()
    JENKINS_CONFIG = get_redis_data('cicd-jenkins')
    jbuild = JenkinsBuild(JENKINS_CONFIG['url'], username=JENKINS_CONFIG['user'],
                          password=JENKINS_CONFIG['password'], job_id=job_id, appinfo_id=appinfo_id, job_type=job_type)
    count = 0
    _flag = True
    while _flag:
        time.sleep(0.1)
        count += 1
        try:
            job_name, job, _ = jbuild.job_info()
            if job_name and job:
                if job.build_number == 0:
                    continue
            ok, message = jbuild.log_console()
            if ok:
                _flag = False
            async_to_sync(channel_layer.send)(
                channel_name,
                {
                    "type": "send.message",
                    "message": message
                }
            )
            if count > 600 or _flag is False:
                async_to_sync(channel_layer.send)(
                    channel_name,
                    {
                        "type": "send.message",
                        "message": 'devops-done'
                    }
                )
                break
        except BaseException as e:
            logger.exception(f'jenkins_log_console err: {e}')
            continue
