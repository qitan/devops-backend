#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
@Author  : Charles Lai
@Contact : qqing_lai@hotmail.com
@Time    : 2020/5/13 下午5:08
@FileName: routing.py
@Blog    : https://blog.imaojia.com
"""

from django.urls import re_path

from deploy.consumers import BuildJobStageOutput, BuildJobConsoleOutput, WatchK8s, WatchK8sLog, \
    WatchK8sDeployment

websocket_urlpatterns = [
    re_path('ws/build/(?P<service_id>[0-9]+)/(?P<job_id>[0-9]+)/(?P<job_type>[^/]+)/stage/$',
            BuildJobStageOutput.as_asgi()),
    re_path('ws/build/(?P<service_id>[0-9]+)/(?P<job_id>[0-9]+)/(?P<job_type>[^/]+)/console/$',
            BuildJobConsoleOutput.as_asgi()),
    re_path(
        'ws/kubernetes/(?P<cluster_id>[0-9]+)/(?P<namespace>[^/]+)/(?P<service>[^/]+)/watch/$', WatchK8s.as_asgi()),
    re_path(
        'ws/kubernetes/(?P<cluster_id>[0-9]+)/(?P<namespace>[^/]+)/(?P<pod>[^/]+)/log/$', WatchK8sLog.as_asgi()),
    re_path(
        'ws/kubernetes/(?P<job_id>[0-9]+)/(?P<app_id>[^/]+)/deployment/$', WatchK8sDeployment.as_asgi()),
]
