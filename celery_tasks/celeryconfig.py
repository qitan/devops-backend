#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
@Author  : Charles Lai
@Contact : qqing_lai@hotmail.com
@Time    : 2020/6/19 下午3:37
@FileName: celeryconfig.py
@Company : Vision Fund
"""

from __future__ import unicode_literals

from celery.schedules import crontab

import datetime

from devops_backend import settings
from config import CELERY_CONFIG

import os
import pytz


def now_func(): return datetime.datetime.now(pytz.timezone(settings.TIME_ZONE))


os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'devops_backend.settings')

# 使用 django logging 配置
EREBUS_WORKER_HIJACK_ROOT_LOGGER = False
CELERY_DEFAULT_QUEUE = CELERY_CONFIG.get('queue', 'celery')
# 设置结果存储
if CELERY_CONFIG['result_backend'].get('startup_nodes', None):
    # 存在startup_nodes配置项，使用集群redis
    CELERY_RESULT_BACKEND = 'common.CeleryRedisClusterBackend.RedisClusterBackend'
    CELERY_REDIS_CLUSTER_SETTINGS = {'startup_nodes': CELERY_CONFIG['result_backend']['startup_nodes'],
                                     'password': CELERY_CONFIG['result_backend']['password_cluster']}
else:
    CELERY_RESULT_BACKEND = f"redis://:{CELERY_CONFIG['result_backend'].get('password', '')}@{CELERY_CONFIG['result_backend']['host']}:{CELERY_CONFIG['result_backend']['port']}/{CELERY_CONFIG['result_backend']['db']}"
CELERY_RESULT_SERIALIZER = 'json'
# 设置代理人broker
BROKER_URL = f"redis://:{CELERY_CONFIG['result_backend'].get('password', '')}@{CELERY_CONFIG['broker_url']['host']}:{CELERY_CONFIG['broker_url']['port']}/{CELERY_CONFIG['broker_url']['db']}"
CELERYD_FORCE_EXECV = True
CELERY_ENABLE_UTC = True
CELERY_TIMEZONE = settings.TIME_ZONE
DJANGO_CELERY_BEAT_TZ_AWARE = False
CELERYBEAT_SCHEDULE = {
}
