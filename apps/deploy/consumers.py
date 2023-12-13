#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
@Author  : Charles Lai
@Contact : qqing_lai@hotmail.com
@Time    : 2020/5/13 下午5:04
@FileName: consumers.py
@Blog    : https://blog.imaojia.com
"""

import json
import time
import os
import signal
from ruamel import yaml
from channels.generic.websocket import WebsocketConsumer
from asgiref.sync import async_to_sync

from kubernetes import client, config, watch
from kubernetes.client import ApiClient

from django.core.cache import caches
from dbapp.models import BuildJob
from dbapp.models import KubernetesCluster, AppInfo

from common.utils.JenkinsAPI import GlueJenkins
from common.utils.RedisAPI import RedisManage
from common.ext_fun import get_redis_data, k8s_cli
from common.utils.AesCipher import AesCipher
from celery_tasks.tasks import watch_k8s_deployment, watch_k8s_pod, tail_k8s_log, jenkins_log_stage, jenkins_log_console
from threading import Thread
import logging

logger = logging.getLogger(__name__)
RUNNING_STAT = ['IN_PROGRESS', 'NOT_EXECUTED', 'QUEUE_WAIT']


class CustomWebsocketConsumer(WebsocketConsumer):
    def __init__(self, *args, **kwargs):
        super(CustomWebsocketConsumer, self).__init__(*args, **kwargs)

    def __del__(self):
        """
        :return:
        """
        if self.result:
            pass


class WatchK8sDeployment(CustomWebsocketConsumer):

    def connect(self):
        self.job_id = self.scope['url_route']['kwargs']['job_id']
        self.app_id = self.scope['url_route']['kwargs']['app_id']
        self.result = watch_k8s_deployment.apply_async(
            [self.channel_name, self.job_id, self.app_id], countdown=1)
        self.accept()

    def disconnect(self, code):
        self.close()

    def receive(self, text_data=None, bytes_data=None):
        text_data_json = json.loads(text_data)
        if text_data_json.get('message', None) == 'abort':
            self.disconnect(0)
        if text_data_json.get('heart', None) == 1:
            self.send(text_data=json.dumps(
                {'message': {'status': 9, 'data': 'pong'}}
            ))

    def send_message(self, event):
        msg = event['message']
        if msg == 'devops-done':
            print('task end')
            self.disconnect(0)
        self.send(text_data=json.dumps({
            'message': {'status': 0, 'data': msg}
        }))


class WatchK8s(WebsocketConsumer):

    def connect(self):
        self.cluster_id = self.scope['url_route']['kwargs']['cluster_id']
        self.service = self.scope['url_route']['kwargs']['service']
        self.namespace = self.scope['url_route']['kwargs']['namespace']
        self.result = None
        self.log_watch_jobs = None
        self.accept()

    def disconnect(self, code):
        self.close()

    def receive(self, text_data=None, bytes_data=None):
        text_data_json = json.loads(text_data)
        if 'logWatch' in text_data_json:
            self.log_watch_jobs = {}
            for pod_name in text_data_json['logWatch']:
                log_lines = text_data_json.get('logLines', 100)
                self.log_watch_jobs[pod_name] = tail_k8s_log.delay(self.channel_name, pod_name, self.namespace,
                                                                   self.cluster_id, log_lines)
        else:
            self.result = watch_k8s_pod.delay(
                self.channel_name, self.cluster_id, self.namespace, self.service)

        if text_data_json.get('message', None) == 'abort':
            if self.result:
                self.result.revoke(terminate=True)
            if self.log_watch_jobs:
                for pod_name, job in self.log_watch_jobs.items():
                    job.revoke(terminate=True)
            self.close()
            return
        if text_data_json.get('heart', None) == 1:
            self.send(text_data=json.dumps(
                {'message': {'status': 9, 'data': 'pong'}}
            ))
            return

    def send_message(self, event):
        logger.debug(f'event --- {event}')
        msg = event['message']
        if msg == 'devops-done':
            print('task end')
            self.close()
        data = {
            'message': {'status': 0, 'data': msg}
        }
        if event.get('pod'):
            data['pod'] = event.get('pod')
        self.send(text_data=json.dumps(data))


class WatchK8sLog(CustomWebsocketConsumer):

    def connect(self):
        self.cluster_id = self.scope['url_route']['kwargs']['cluster_id']
        self.namespace = self.scope['url_route']['kwargs']['namespace']
        self.pod = self.scope['url_route']['kwargs']['pod']
        self.lines = self.scope['query_string'].decode('utf-8').split('=')[-1]
        self.result = tail_k8s_log.delay(
            self.channel_name, self.pod, self.namespace, self.cluster_id, self.lines)
        self.accept()

    def disconnect(self, code):
        self.close()

    def receive(self, text_data=None, bytes_data=None):
        text_data_json = json.loads(text_data)
        if text_data_json.get('message', None) == 'abort':
            self.result.revoke(terminate=True)
            self.close()
        if text_data_json.get('heart', None) == 1:
            self.send(text_data=json.dumps(
                {'message': {'status': 9, 'data': 'pong'}}
            ))

    def send_message(self, event):
        msg = event['message']
        if msg == 'devops-done':
            print('task end')
            self.close()
        self.send(text_data=json.dumps({
            'message': {'status': 0, 'data': msg}
        }))


class BuildJobConsoleOutput(CustomWebsocketConsumer):

    def connect(self):
        self.appinfo_id = self.scope['url_route']['kwargs'].get(
            'service_id', 0)
        self.job_id = self.scope['url_route']['kwargs']['job_id']
        self.job_type = self.scope['url_route']['kwargs'].get(
            'job_type', 'app')
        self.result = jenkins_log_console.delay(
            self.channel_name, self.job_id, self.appinfo_id, self.job_type)
        self.accept()

    def disconnect(self, code):
        self.close()

    def receive(self, text_data=None, bytes_data=None):
        text_data_json = json.loads(text_data)
        if text_data_json.get('message', None) == 'abort':
            self.disconnect(0)
            # self.close()
        if text_data_json.get('heart', None) == 1:
            self.send(text_data=json.dumps(
                {'message': {'status': 9, 'data': 'pong'}}
            ))

    def send_message(self, event):
        msg = event['message']
        if msg == 'devops-done':
            print('task end')
            self.disconnect(0)
        self.send(text_data=json.dumps({
            'message': msg
        }))

        msg = event['message']
        if msg == 'devops-done':
            print('task end')
            self.disconnect(0)
            self.close()
        self.send(text_data=json.dumps({
            'message': msg
        }))


class BuildJobStageOutput(CustomWebsocketConsumer):

    def connect(self):
        self.appinfo_id = self.scope['url_route']['kwargs'].get(
            'service_id', 0)
        self.job_id = self.scope['url_route']['kwargs']['job_id']
        self.job_type = self.scope['url_route']['kwargs'].get(
            'job_type', 'app')
        self.rec_id = self.scope['query_string'].decode('utf-8').split('=')[-1]
        self.result = jenkins_log_stage.apply_async(
            args=[self.channel_name, self.job_id, self.appinfo_id, self.job_type], countdown=-1)
        self.accept()

    def disconnect(self, code):
        self.close()

    def receive(self, text_data=None, bytes_data=None):
        text_data_json = json.loads(text_data)
        if text_data_json.get('message', None) == 'abort':
            self.disconnect(0)
        if text_data_json.get('heart', None) == 1:
            self.send(text_data=json.dumps(
                {'message': {'status': 9, 'data': 'pong'}}
            ))

    def send_message(self, event):
        msg = event['message']
        if msg == 'devops-done':
            print('task end')
            self.disconnect(0)
            # self.close()
        self.send(text_data=json.dumps({
            'message': msg
        }))
