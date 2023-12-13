#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
@Author  : Charles Lai
@Contact : qqing_lai@hotmail.com
@Time    : 2020/5/19 下午5:44
@FileName: celery.py
@Company : Vision Fund
"""

from __future__ import unicode_literals

from celery import Celery
from django.conf import settings
from celery_tasks import celeryconfig
import os
from ansible import constants as C

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'devops_backend.settings')

app = Celery('celery_tasks')
app.config_from_object(celeryconfig)

app.autodiscover_tasks(settings.INSTALLED_APPS)
