#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
@Author  : Charles Lai
@Contact : qqing_lai@hotmail.com
@Time    : 2020/4/21 下午5:06
@FileName: AnsibleAPI.py
"""

import os
import json
import shortuuid

from ansible.parsing.dataloader import DataLoader
from ansible.vars.manager import VariableManager
from ansible.inventory.manager import InventoryManager
from ansible.playbook.play import Play
from ansible.executor.task_queue_manager import TaskQueueManager
from ansible.executor.playbook_executor import PlaybookExecutor
from ansible.plugins.callback import CallbackBase
from ansible import context
from ansible.inventory.host import Host
from ansible.errors import AnsibleError, AnsibleParserError

from optparse import Values
import logging

logger = logging.getLogger(__name__)


class HostInventory(Host):
    def __init__(self, host_data):
        self.host_data = host_data
        hostname = host_data.get('hostname') or host_data.get('ip')
        port = host_data.get('port') or 22
        super(HostInventory, self).__init__(hostname, port)
        self.__set_required_variables()
        self.__set_extra_variables()

    def __set_required_variables(self):
        host_data = self.host_data
        self.set_variable('ansible_host', host_data['ip'])
        self.set_variable('ansible_port', host_data['port'])
        if host_data.get('username'):
            self.set_variable('ansible_user', host_data['username'])
        if host_data.get('password'):
            self.set_variable('ansible_ssh_pass', host_data['password'])
        if host_data.get('private_key'):
            self.set_variable('ansible_ssh_private_key_file',
                              host_data['private_key'])

    def __set_extra_variables(self):
        for k, v in self.host_data.get('vars', {}).items():
            self.set_variable(k, v)

    def __repr__(self):
        return self.name


class DynamicInventory(InventoryManager):
    def __init__(self, resource=None):
        self.resource = resource
        self.loader = DataLoader()
        self.variable_manager = VariableManager()
        super(DynamicInventory, self).__init__(self.loader)

    def get_groups(self):
        return self._inventory.groups

    def get_group(self, name):
        return self._inventory.groups.get(name, None)

    def parse_sources(self, cache=False):
        group_all = self.get_group('all')
        ungrouped = self.get_group('ungrouped')
        if isinstance(self.resource, list):
            for host_data in self.resource:
                host = HostInventory(host_data=host_data)
                self.hosts[host_data['hostname']] = host
                groups_data = host_data.get('groups')
                if groups_data:
                    for group_name in groups_data:
                        group = self.get_group(group_name)
                        if group is None:
                            self.add_group(group_name)
                            group = self.get_group(group_name)
                        group.add_host(host)
                else:
                    ungrouped.add_host(host)
                group_all.add_host(host)

        elif isinstance(self.resource, dict):
            for k, v in self.resource.items():
                group = self.get_group(k)
                if group is None:
                    self.add_group(k)
                    group = self.get_group(k)
                if 'hosts' in v:
                    if not isinstance(v['hosts'], list):
                        raise AnsibleError(
                            "You defined a group '%s' with bad data for the host list:\n %s" % (group, v))
                    for host_data in v['hosts']:
                        host = HostInventory(host_data=host_data)
                        self.hosts[host_data['hostname']] = host
                        group.add_host(host)

                if 'vars' in v:
                    if not isinstance(v['vars'], dict):
                        raise AnsibleError(
                            "You defined a group '%s' with bad data for variables:\n %s" % (group, v))

                    for x, y in v['vars'].items():
                        self._inventory.groups[k].set_variable(x, y)

    def get_matched_hosts(self, pattern):
        return self.get_hosts(pattern)


def get_inventory(hosts):
    if isinstance(hosts, str):
        if os.path.isfile(hosts):
            return InventoryManager(loader=DataLoader(), sources=hosts)
        else:
            return False
    else:
        return DynamicInventory(hosts)


class ResultCallback(CallbackBase):
    def __init__(self, *args, **kwargs):
        super(ResultCallback, self).__init__(*args, **kwargs)
        self.host_ok = {}
        self.task_ok = {}
        self.host_unreachable = {}
        self.host_failed = {}

    def v2_runner_on_unreachable(self, result):
        self.host_unreachable[result._host.get_name()] = result

    def v2_runner_on_ok(self, result, *args, **kwargs):
        self.host_ok[result._host.get_name()] = result

    def v2_runner_on_failed(self, result, *args, **kwargs):
        self.host_failed[result._host.get_name()] = result


class PlayBookResultsCollector(CallbackBase):
    CALLBACK_VERSION = 2.0

    def __init__(self, *args, **kwargs):
        super(PlayBookResultsCollector, self).__init__(*args, **kwargs)
        self.task_ok = {}
        self.task_skipped = {}
        self.task_failed = {}
        self.task_status = {}
        self.task_unreachable = {}
        self.task_changed = {}
        logger.debug(f'self === {self}')

    def v2_runner_on_ok(self, result, *args, **kwargs):
        self.task_ok[result._host.get_name()] = result

    def v2_runner_on_failed(self, result, *args, **kwargs):
        self.task_failed[result._host.get_name()] = result

    def v2_runner_on_unreachable(self, result):
        self.task_unreachable[result._host.get_name()] = result

    def v2_runner_on_skipped(self, result):
        self.task_skipped[result._host.get_name()] = result

    def v2_runner_on_changed(self, result):
        self.task_changed[result._host.get_name()] = result

    def v2_playbook_on_stats(self, stats):
        hosts = sorted(stats.processed.keys())
        for h in hosts:
            t = stats.summarize(h)
            self.task_status[h] = {
                "ok": t['ok'],
                "changed": t['changed'],
                "unreachable": t['unreachable'],
                "skipped": t['skipped'],
                "failed": t['failures']
            }


class AnsibleApi(object):
    def __init__(self, inventory, become=None, flush_cache=None, extra_vars={}):
        self.become = become
        self.options = {'verbosity': 0, 'ask_pass': False, 'private_key_file': None, 'remote_user': None,
                        'connection': 'smart', 'timeout': 10, 'ssh_common_args': '-o StrictHostKeyChecking=no',
                        'sftp_extra_args': '',
                        'scp_extra_args': '', 'ssh_extra_args': '', 'force_handlers': False, 'flush_cache': flush_cache,
                        'become': None, 'become_method': 'sudo', 'become_user': None, 'become_ask_pass': False,
                        'tags': ['all'], 'skip_tags': [], 'check': False, 'syntax': None, 'diff': False,
                        'listhosts': None, 'subset': None, 'extra_vars': extra_vars, 'ask_vault_pass': False,
                        'vault_password_files': [], 'vault_ids': [], 'forks': 5, 'module_path': None, 'listtasks': None,
                        'listtags': None, 'step': None, 'start_at_task': None, 'args': ['fake']}
        self.ops = Values(self.options)

        context._init_global_context(self.ops)
        self.loader = DataLoader()
        self.passwords = dict()
        self.results_callback = ResultCallback()
        self.playbook_callback = PlayBookResultsCollector()
        self.inventory = get_inventory(inventory)
        self.variable_manager = VariableManager(
            loader=self.loader, inventory=self.inventory)
        extra_vars['use_cache'] = False
        self.variable_manager._extra_vars = extra_vars

    def complete_notify(self):
        pass

    def runansible(self, host_list, task_list):
        play_source = dict(
            name=shortuuid.ShortUUID().random(),
            hosts=host_list,
            become=self.become,
            gather_facts='no',
            tasks=task_list
        )
        play = Play().load(play_source, variable_manager=self.variable_manager, loader=self.loader)

        tqm = None
        try:
            tqm = TaskQueueManager(
                inventory=self.inventory,
                variable_manager=self.variable_manager,
                loader=self.loader,
                # options=self.ops,
                passwords=self.passwords,
                stdout_callback=self.results_callback,
                run_tree=False,
            )
            result = tqm.run(play)
        finally:
            if tqm is not None:
                tqm.cleanup()

        results_raw = {}
        results_raw['success'] = {}
        results_raw['failed'] = {}
        results_raw['unreachable'] = {}

        for host, result in self.results_callback.host_ok.items():
            results_raw['success'][host] = json.dumps(result._result)

        for host, result in self.results_callback.host_failed.items():
            results_raw['failed'][host] = result._result['msg']

        for host, result in self.results_callback.host_unreachable.items():
            results_raw['unreachable'][host] = result._result['msg']

        self.complete_notify()
        return results_raw

    def playbookrun(self, playbook_path):
        context._init_global_context(self.ops)

        playbook = PlaybookExecutor(playbooks=playbook_path,
                                    inventory=self.inventory,
                                    variable_manager=self.variable_manager,
                                    loader=self.loader, passwords=self.passwords)
        playbook._tqm._stdout_callback = self.playbook_callback

        try:
            result = playbook.run()
            logger.debug(f'playbook.run  result === {result}')
            results_raw = {}
            results_raw['success'] = {}
            results_raw['failed'] = {}
            results_raw['unreachable'] = {}

            for host, result in self.playbook_callback.task_ok.items():
                results_raw['success'][host] = result._result

            for host, result in self.playbook_callback.task_failed.items():
                results_raw['failed'][host] = result._result['msg']

            for host, result in self.playbook_callback.task_unreachable.items():
                results_raw['unreachable'][host] = result._result['msg']

            logger.debug(
                f'playbook_callback dict === {self.playbook_callback.__dict__}')
            self.complete_notify()
            return results_raw
        except Exception as e:
            logger.exception(
                f'ansible api playbookrun error ==== {e.__class__} {e}')
            raise e
