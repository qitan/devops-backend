#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
@Author : Charles Lai
@Contact : qqing_lai@hotmail.com
@Time : 2020/12/1 下午4:05
@FileName: AnsibleCallback.py
@Blog ：https://imaojia.com
"""

from __future__ import unicode_literals

from common.utils.AnsibleAPI import AnsibleApi as BaseAnsibleApi
from common.utils.AnsibleAPI import PlayBookResultsCollector as BasePlayBookResultsCollector
import json
import logging

logger = logging.getLogger(__name__)


class PlayBookResultsCollector(BasePlayBookResultsCollector):

    def __init__(self, redis_conn, chan, jid, channel, *args, debug=False, on_any_callback=None, **kwargs):
        super(PlayBookResultsCollector, self).__init__(*args, **kwargs)
        self.channel = channel
        self.jid = jid
        self.chan = chan
        self.redis_conn = redis_conn
        self.debug = debug
        self.on_any_callback = on_any_callback

    @staticmethod
    def result_pop(result):
        try:
            result._result['container'].pop('ResolvConfPath', None)
            result._result['container'].pop('HostnamePath', None)
            result._result['container'].pop('HostsPath', None)
            result._result['container'].pop('Platform', None)
            result._result['container'].pop('HostConfig', None)
            result._result['container'].pop('GraphDriver', None)
            result._result['container'].pop('NetworkSettings', None)
        except:
            pass
        if 'stdout' in result._result and 'stdout_lines' in result._result:
            result._result['stdout_lines'] = '<omitted>'
        if 'results' in result._result:
            for i in result._result['results']:
                if 'stdout' in i and 'stdout_lines' in i:
                    i['stdout_lines'] = '<omitted>'
        return result

    def v2_runner_on_ok(self, result, *args, **kwargs):
        'ansible_facts' in result._result and result._result.pop(
            'ansible_facts')
        'invocation' in result._result and result._result.pop('invocation')
        result = self.result_pop(result)
        res = {
            'status': 'success',
            'step_status': 'success',
            'host': result._host.get_name(),
            'task': result._task.get_name(),
            'msg': result._result
        }

        self.redis_conn.rpush(self.jid, json.dumps(
            {res['task']: {res['host']: res}}))
        self.redis_conn.rpush('%s:%s:status' % (self.jid, res['task']), 0)
        self.task_ok[result._host.get_name()] = result
        logger.debug(f'v2_runner_on_ok ======== {self.task_ok}')

    def v2_runner_on_failed(self, result, *args, **kwargs):
        'ansible_facts' in result._result and result._result.pop(
            'ansible_facts')
        'invocation' in result._result and result._result.pop('invocation')
        result = self.result_pop(result)
        res = {
            'status': 'failed',
            'step_status': 'error',
            'host': result._host.get_name(),
            'task': result._task.get_name(),
            'msg': result._result
        }
        self.redis_conn.rpush(self.jid, json.dumps(
            {res['task']: {res['host']: res}}))
        self.redis_conn.rpush('%s:%s:status' % (self.jid, res['task']), 1)
        self.task_failed[result._host.get_name()] = result
        logger.debug(f'v2_runner_on_failed ======== {self.task_failed}')

    def v2_runner_on_unreachable(self, result):
        'ansible_facts' in result._result and result._result.pop(
            'ansible_facts')
        'invocation' in result._result and result._result.pop('invocation')
        result = self.result_pop(result)
        res = {
            'status': 'unreachable',
            'step_status': 'error',
            'host': result._host.get_name(),
            'task': result._task.get_name(),
            'msg': result._result
        }
        self.redis_conn.rpush(self.jid, json.dumps(
            {res['task']: {res['host']: res}}))
        self.redis_conn.rpush('%s:%s:status' % (self.jid, res['task']), 1)
        self.task_unreachable[result._host.get_name()] = result
        logger.debug(
            f'v2_runner_on_unreachable ======== {self.task_unreachable}')

    def v2_runner_on_skipped(self, result):
        'ansible_facts' in result._result and result._result.pop(
            'ansible_facts')
        'invocation' in result._result and result._result.pop('invocation')
        result = self.result_pop(result)
        res = {
            'status': 'skipped',
            'step_status': 'finish',
            'host': result._host.get_name(),
            'task': result._task.get_name(),
            'msg': result._result
        }
        self.redis_conn.rpush(self.jid, json.dumps(
            {res['task']: {res['host']: res}}))
        self.redis_conn.rpush('%s:%s:status' % (self.jid, res['task']), 0)
        self.task_skipped[result._host.get_name()] = result
        logger.debug(f'v2_runner_on_skipped ======== {self.task_skipped}')

    def v2_runner_on_changed(self, result):
        'ansible_facts' in result._result and result._result.pop(
            'ansible_facts')
        'invocation' in result._result and result._result.pop('invocation')
        result = self.result_pop(result)
        res = {
            'status': 'onchanged',
            'step_status': 'finish',
            'host': result._host.get_name(),
            'task': result._task.get_name(),
            'msg': result._result
        }
        self.redis_conn.rpush(self.jid, json.dumps(
            {res['task']: {res['host']: res}}))
        self.redis_conn.rpush('%s:%s:status' % (self.jid, res['task']), 0)
        self.task_changed[result._host.get_name()] = result
        logger.debug(f'v2_runner_on_changed ======== {self.task_changed}')

    def v2_playbook_on_no_hosts_matched(self):
        res = {
            'task': '查找主机',
            'status': 'unreachable',
            'step_status': 'error',
            'host': 'unmatched',
            'msg': {'result': 'Could not match supplied host'}
        }
        self.redis_conn.rpush(self.jid, json.dumps(
            {res['task']: {res['host']: res}}))
        self.redis_conn.rpush('%s:%s:status' % (self.jid, res['task']), 0)

    def v2_on_any(self, result, *args, **kwargs):
        if self.on_any_callback:
            self.on_any_callback(self, result, *args, **kwargs)


class AnsibleApi(BaseAnsibleApi):
    def __init__(self, redis_conn, chan, jid, channel, *args, on_any_callback=None, **kwargs):
        super(AnsibleApi, self).__init__(*args, **kwargs)

        self.playbook_callback = PlayBookResultsCollector(redis_conn, chan, jid, channel,
                                                          on_any_callback=on_any_callback)
        self.channel = channel
        self.redis_conn = redis_conn
        self.jid = jid
