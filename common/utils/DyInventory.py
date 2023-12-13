#!/usr/bin/python3
# -*- coding: utf-8 -*-
"""
@Author : Charles Lai
@Contact : qqing_lai@hotmail.com
@Time : 2020/12/8 上午10:26
@FileName: DyInventory.py
@Blog ：https://imaojia.com
"""

import os
import requests
import argparse

try:
    import json
except ImportError:
    import simplejson as json


class DyInventory(object):
    def __init__(self, url, username, password):
        self.__url = url
        self.__username = username
        self.__password = password
        self.__headers = {'Content-Type': 'application/json;charset=UTF-8'}

        self.inventory = {}
        self.read_cli_args()
        # self Called with `--list`.
        if self.args.list:
            self.inventory = self.get_hosts()
            print(json.dumps(self.inventory, indent=4))
        elif self.args.host:
            # Not implemented, since we return _meta info `--list`.
            # self.inventory = self.empty_inventor()
            host = self.get_host_detail(self.args.host)
            print(json.dumps(host, indent=4))
        # If no groups or vars are present, return empty inventory.
        else:
            self.inventory = self.empty_inventor()
            print(json.dumps(self.inventory, indent=4))

    def get_token(self):
        url = f"{self.__url}/api/soms/user/login/"
        data = {'username': self.__username, 'password': self.__password}
        r = requests.post(url=url, json=data, headers=self.__headers)
        if r.status_code == 200:
            return r.json()['data']['access']
        else:
            raise Exception('get token err')

    def get_hosts(self):
        app_id = os.environ['APP_ID']
        env = os.environ['APP_ENV']
        token = self.get_token()
        url = f"{self.__url}/api/soms/app/service/asset/?app_id={app_id}&environment={env}"
        self.__headers['Authorization'] = f"Bearer {token}"
        r = requests.get(url, headers=self.__headers)
        if r.status_code == 200:
            return r.json()['data']
        else:
            raise Exception('get hosts err')

    # Empty inventory for testing.
    def empty_inventor(self):
        if not self.args.host:
            return {'_meta': {'hostvars': {}}}
        data = self.get_hosts()
        var = data.get('_meta', {}).get('hostvars', {}).get(self.args.host, '')
        return var or {}

    def get_host_detail(self, host):
        data = self.get_hosts()['_meta']['hostvars'][host]
        return {'ansible_ssh_host': data['hostname'], 'ansible_ssh_port': data['port'],
                'ansible_ssh_user': data['username'], 'ansible_ssh_pass': data['password']}

    # Read the command line args passed to the script.
    def read_cli_args(self):
        parser = argparse.ArgumentParser()
        parser.add_argument('--list', action='store_true')
        parser.add_argument('--host', action='store')
        parser.add_argument('--app', action='store')
        parser.add_argument('--env', action='store')
        self.args = parser.parse_args()
