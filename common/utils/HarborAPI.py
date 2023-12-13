#!/usr/bin/env python
# -*- encoding: utf-8 -*-
'''
@Author  :    Charles Lai
@Contact :    qqing_lai@hotmail.com
@Time    :    2021/07/14 18:14
@FileName:    HarborAPI.py
@Blog    :    https://imaojia.com
'''

from __future__ import unicode_literals

import base64
import ssl

import requests

import logging

logger = logging.getLogger('drf')

ssl._create_default_https_context = ssl._create_unverified_context


class HarborAPI(object):
    def __init__(self, url, username, password):
        self.__url = url.rstrip('/')
        self.__user = username
        self.__password = password
        self.__token = base64.b64encode(
            bytes('%s:%s' % (self.__user, self.__password), encoding='utf-8'))
        self.__headers = dict()
        self.__headers["Accept"] = "application/json"
        self.__headers['authorization'] = 'Basic %s' % str(
            self.__token, encoding='utf-8')

    def request(self, method, obj=None, prefix='/'):
        try:
            if method == 'get':
                req = requests.request(method, '%s%s' % (self.__url, prefix), params=obj, headers=self.__headers,
                                       verify=False)
                if req.status_code > 399:
                    return {'ecode': req.status_code, 'message': f'{req.content}\n{req.reason}'}
                res = {'ecode': req.status_code, 'data': req.json(), 'count': req.headers.get('X-Total-Count', None),
                       'next': req.headers.get('Link', None)}
            if method == 'delete':
                req = requests.request(method, '%s%s' % (
                    self.__url, prefix), headers=self.__headers, verify=False)
                if req.status_code > 399:
                    return {'ecode': req.status_code, 'message': f'{req.content}\n{req.reason}'}
                res = {'ecode': req.status_code, 'data': req.content}
            if method in ['put', 'post']:
                req = requests.request(method, '%s%s' % (self.__url, prefix), json=obj, headers=self.__headers,
                                       verify=False)
                if req.status_code > 399:
                    return {'ecode': req.status_code, 'message': f'{req.content}\n{req.reason}'}
                res = {'ecode': req.status_code, 'data': req.content}
            if method == 'head':
                req = requests.request(method, '%s%s' % (
                    self.__url, prefix), headers=self.__headers, verify=False)
                if req.status_code > 399:
                    return {'ecode': req.status_code, 'message': f'{req.content}\n{req.reason}'}
                res = {'ecode': req.status_code, 'data': req.content}
        except BaseException as e:
            raise e
        return res

    def systeminfo(self):
        res = self.request('get', prefix='/systeminfo')
        return res

    def get_users(self):
        res = self.request('get', prefix='/users')
        return res

    def get_projects(self, project_name=None, page=1, page_size=20):
        """
        :project_name: The name of project
        :page: default is 1.
        :page_size: default is 10, maximum is 100.
        """
        params = {'page': page, 'page_size': page_size}
        if project_name:
            params['name'] = project_name
        try:
            res = self.request('get', params, prefix='/projects')
            return res
        except BaseException as e:
            return {'ecode': 500, 'message': e}

    def get_repositories(self, project_id, page=1, page_size=20, repo=None):
        params = {'project_id': project_id,
                  'page': page, 'page_size': page_size}
        if repo:
            params['q'] = repo
        try:
            res = self.request('get', params, '/repositories')
            return res
        except BaseException as e:
            return {'ecode': 500, 'message': e}

    def get_tags(self, repo):
        try:
            res = self.request('get', prefix='/repositories/%s/tags' % repo)
            tags = [
                {'name': i['name'], 'created': i['created'], 'push_time': i.get(
                    'push_time', None), 'size': i['size']}
                for i in
                res['data']]
            tags.sort(key=lambda k: (k.get('created')), reverse=True)
            return {'ecode': 200, 'data': tags, 'count': len(tags)}
        except BaseException as e:
            return {'ecode': 500, 'message': e}

    def fetch_project(self, project_id):
        """
        获取项目信息
        """
        try:
            res = self.request(
                'get', {'project_id': project_id}, prefix=f'/projects/{project_id}')
            return res
        except BaseException as e:
            return {'ecode': 500, 'message': e}

    def fetch_tag(self, repo, tag):
        """
        获取指定镜像标签
        """
        try:
            res = self.request(
                'get', prefix=f'/repositories/{repo}/tags/{tag}')
            return res
        except BaseException as e:
            return {'ecode': 500, 'message': e}

    def create_project(self, project_name, public=True):
        """
        创建仓库项目
        """
        try:
            data = {'project_name': project_name, 'metadata': {
                'public': 'true' if public else 'false'}}
            res = self.request('post', obj=data, prefix='/projects')
            return res
        except BaseException as e:
            return {'ecode': 500, 'message': e}

    def update_project(self, project_id, *args, **kwargs):
        """
        更新仓库项目
        """
        try:
            res = self.request('put', obj=kwargs,
                               prefix=f'/projects/{project_id}')
            return res
        except BaseException as e:
            return {'ecode': 500, 'message': e}

    def project_exists(self, project_name):
        """
        查询项目是否存在
        """
        try:
            res = self.request(
                'head', prefix=f'/projects?project_name={project_name}')
            return res
        except BaseException as e:
            return {'ecode': 500, 'message': e}

    def patch_tag(self, repo, src_image, tag_name):
        """
        镜像打标签
        """
        try:
            try:
                # 创建仓库项目
                res = self.create_project(repo.split('/')[0])
            except BaseException as e:
                pass
            data = {'tag': tag_name, 'src_image': src_image, 'override': True}
            res = self.request(
                'post', obj=data, prefix='/repositories/%s/tags' % repo)
            return res
        except BaseException as e:
            return {'ecode': 500, 'message': e}

    def delete_tag(self, repo, tag):
        """
        删除标签
        """
        try:
            res = self.request(
                'delete', prefix=f'/repositories/{repo}/tags/{tag}')
            return res
        except BaseException as e:
            logger.ex
            return {'ecode': 500, 'message': e}

    def search(self, query):
        """
        搜索
        """
        try:
            res = self.request('get', {'q': query}, prefix='/search')
            return res
        except BaseException as e:
            logger.exception(e)
            return {'ecode': 500, 'message': e}
