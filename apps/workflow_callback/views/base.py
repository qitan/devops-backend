#!/usr/bin/env python
# -*- encoding: utf-8 -*-
'''
@author  :   Charles Lai
@file    :   base.py
@time    :   2023/03/16 22:00
@contact :   qqing_lai@hotmail.com
@company :   IMAOJIA Co,Ltd
'''

# here put the import lib
import asyncio
import logging
from typing import Any

from django.db import close_old_connections, connection

from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView

from dbapp.models import Workflow

logger = logging.getLogger(__name__)


def get_form_item_name(node_conf, cname):
    for field_conf in node_conf['form_models']:
        field_name = field_conf['field']
        field_cname = field_conf['title']
        if field_cname == cname:
            return field_name


class CallbackAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get_workflow(self, request):
        try:
            wid = request.data['workflow']['wid']
            wf = Workflow.objects.get(wid=wid)
            return wf
        except BaseException as e:
            logger.info(f'获取不到工单ID，原因：{e}')
            raise Exception('获取不到工单ID')

    def set_status(self, wf, status):
        wf.status = getattr(Workflow.STATUS, status)
        wf.save()

    def task_queue(self, *args):
        pass

    def handler(self, *args):
        tasks = self.task_queue(*args)
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        results = []
        try:
            results = loop.run_until_complete(asyncio.gather(*tasks))
        except BaseException as e:
            logger.debug(f'err {e}')
            results = [(False, '执行异常')]
        loop.close()
        return results
