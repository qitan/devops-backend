#!/usr/bin/env python
# -*- encoding: utf-8 -*-
'''
@author  :   Charles Lai
@file    :   JiraAPI.py
@time    :   2022/12/05 14:10
@contact :   qqing_lai@hotmail.com
@company :   IMAOJIA Co,Ltd
'''

# here put the import lib
from jira import JIRA
import logging

logger = logging.getLogger(__name__)


class JiraAPI(object):

    def __init__(self, url, user=None, password=None, token=None):
        self.__url = url
        self.__user = user
        self.__password = password
        self.__token = token
        if user and token:
            self.client = JIRA(server=self.__url, basic_auth=(
                self.__user, self.__token))
        elif token:
            self.client = JIRA(server=self.__url, token_auth=self.__token)
        elif user and password:
            self.client = JIRA(server=self.__url, basic_auth=(
                self.__user, self.__password))

    def list_issues(self, issue_text='', issue_key=None, project=None, exclude_status=None, max_results=20):
        """
        获取issues
        :params return: ['expand', 'startAt', 'maxResults', 'total', 'issues']
        """
        params = ''
        if not any([issue_text, issue_key, project]):
            return False, '缺少参数！'
        if issue_key:
            params = f'issueKey={issue_key}'
        if issue_text:
            params = f'text~{issue_text}'
            max_results = 50
        if project:
            params = f'project={project}'
        if exclude_status:
            status = (',').join(exclude_status.split(','))
            params = f'{params} and status not in ({status})'
        try:
            issues = self.client.search_issues(
                params, json_result=True, maxResults=max_results)
            return True, issues
        except BaseException as e:
            return False, e.text

    def get_issue(self, issue_key):
        """
        获取issue详情
        """
        try:
            issue = self.client.issue(issue_key)
            return True, issue
        except BaseException as e:
            return False, e.text

    def update_issue(self, issue_key, **kwargs):
        """
        更新issue
        """
        ok, issue = self.get_issue(issue_key)
        if ok:
            try:
                result = issue.update(**kwargs)
                return True, result
            except BaseException as e:
                return False, e.text
        return False, '获取issue失败.'
