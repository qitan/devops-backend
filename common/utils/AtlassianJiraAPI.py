#!/usr/bin/env python
# -*- encoding: utf-8 -*-
'''
@author  :   Charles Lai
@file    :   AtlassianJiraAPI.py
@time    :   2023/04/14 10:41
@contact :   qqing_lai@hotmail.com
'''

# here put the import lib
from atlassian import Jira

import logging

logger = logging.getLogger(__name__)


class JiraAPI(object):

    def __init__(self, url, user=None, password=None, token=None):
        self.__url = url
        self.__user = user
        self.__password = password
        self.__token = token

        if token:
            self.client = Jira(url=self.__url, token=self.__token)
        elif user and password:
            self.client = Jira(
                url=self.__url, username=self.__user, password=self.__password)
        else:
            raise Exception('未提供认证信息.')

    def list_issues(self, issue_text='', issue_key=None, project=None, include_status=None, exclude_status=None, max_results=20):
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
        if include_status:
            # 存在包含的状态
            status = (',').join(include_status.split(','))
            params = f'{params} and status in ({status})'
        elif exclude_status:
            # 没有配置包含的状态且存在要排除的状态
            status = (',').join(exclude_status.split(','))
            params = f'{params} and status not in ({status})'
        try:
            issues = self.client.jql(params)
            return True, issues
        except BaseException as e:
            logger.debug(f'获取issue异常, {e.__dict__}, {e}')
            return False, str(e)

    def update_issue_status(self, issue_key, status):
        """
        更新issue状态
        """
        try:
            result = self.client.set_issue_status(
                issue_key, status, fields=None)
            logger.debug(f'更新issue状态, result')
            return True, result
        except BaseException as e:
            logger.debug(f'更新issue状态异常，{e}')
            return False, str(e)
