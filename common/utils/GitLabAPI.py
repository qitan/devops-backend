#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
@Author : Charles Lai
@Contact : qqing_lai@hotmail.com
@Time : 2021/1/25 下午3:13
@FileName: GitLabAPI.py
@Blog ：https://imaojia.com
"""

import gitlab

from common.variables import G_COMMIT
import logging

logger = logging.getLogger(__name__)


class GitLabAPI(object):
    def __init__(self, url, user=None, password=None, token=None, oauth=False):
        self.__url = url
        if token:
            self.__token = token
            if oauth:
                params = {'oauth_token': self.__token}
            else:
                params = {'private_token': self.__token}
            self.__gl = gitlab.Gitlab(self.__url, **params)
        else:
            self.__gl = gitlab.Gitlab(
                self.__url, http_username=user, http_password=password)
            self.__gl.auth()

    def get_gl(self):
        return self.__gl

    def list_projects(self, get_all=False, key=None, per_page=20, page=1):
        params = {'per_page': per_page, 'page': page}
        if get_all:
            params = {'get_all': True, 'per_page': per_page}
        if key:
            params['search'] = key
        projects = self.__gl.projects.list(**params)
        return projects

    def get_project(self, project_id=None, project_name_with_namespace=None):
        if any([project_id, project_name_with_namespace]) is False:
            raise Exception('缺少参数，project_id或project_name_with_namespace必选其一.')
        condition = project_id or project_name_with_namespace
        try:
            project = self.__gl.projects.get(condition)
            return project
        except BaseException as e:
            logger.info(e)
            return None

    def create_project(self, name, namespace_id=None, initialize_with_readme=False):
        payload = {'name': name, 'path': name,
                   'initialize_with_readme': initialize_with_readme}
        if namespace_id:
            payload['namespace_id'] = namespace_id
        try:
            ret = self.__gl.projects.create(payload)
            return True, ret
        except BaseException as e:
            logger.exception(f'创建分支请求异常，原因：{e.__dict__}')
            return False, e

    def get_commit(self, commit_id, project_id=None, project_name_with_namespace=None):
        try:
            commit = self.get_project(
                project_id, project_name_with_namespace).get(commit_id)
            return commit
        except BaseException as e:
            logger.info(e)
            return None

    def list_groups(self, get_all=False, key=None, per_page=20, page=1):
        params = {'per_page': per_page, 'page': page}
        if get_all:
            params = {'get_all': True, 'all': True, 'per_page': per_page}
        if key:
            params['search'] = key
        groups = self.__gl.groups.list(**params)
        return [{'id': i.id, 'name': i.name, 'description': i.description} for i in groups if not i.parent_id]

    def create_group(self, name, path=None, desc=None, parent=None):
        """
        创建组
        """
        payload = {'name': name, 'path': path or name,
                   'description': desc or ''}
        if parent:
            payload['parent_id'] = parent
        try:
            group = self.__gl.groups.create(payload)
            return True, group
        except BaseException as e:
            logger.info(e)
            return False, e

    def create_branch(self, project, src_branch, target_branch):
        payload = {'branch': target_branch,
                   'ref': src_branch}
        if isinstance(project, (int,)):
            project = self.get_project(project)
        try:
            ret = project.branches.create(payload)
            return True, ret
        except BaseException as e:
            logger.exception(f'创建分支请求异常，原因：{e.__dict__}')
            return False, e

    def list_branches(self, project_id=None, project_name_with_namespace=None, get_all=False, key=None, per_page=20,
                      page=1, protected='0', *args, **kwargs):
        params = {'per_page': per_page, 'page': page}
        if not protected:
            protected = '0'
        if get_all:
            params = {'get_all': True, 'per_page': per_page}
        if key:
            params['search'] = key
        params.update(kwargs)
        branches = self.get_project(project_id=project_id,
                                    project_name_with_namespace=project_name_with_namespace).branches.list(**params)
        branches = [{'uid': f"{G_COMMIT[0][0]}:{i.name}", 'name': i.name, 'commit': i.commit, 'label': G_COMMIT[0][0], 'protected': i.protected}
                    for i in branches]
        if protected != '0':
            # 过滤受保护分支
            _map = {'1': True, '2': False}
            branches = [i for i in branches if i['protected']
                        == _map[protected]]
        return branches

    def list_protected_branches(self, project_id=None, project_name_with_namespace=None, get_all=False, key=None, per_page=20,
                                page=1, *args, **kwargs):
        params = {'per_page': per_page, 'page': page}
        if get_all:
            params = {'get_all': True, 'per_page': per_page}
        if key:
            params['search'] = key
        params.update(kwargs)
        branches = self.get_project(project_id=project_id,
                                    project_name_with_namespace=project_name_with_namespace).protectedbranches.list(**params)
        branches = [{'uid': f"{G_COMMIT[0][0]}:{i.name}", 'name': i.name, 'commit': i.commit, 'label': G_COMMIT[0][0], 'protected': i.protected}
                    for i in branches]
        return branches

    def list_tags(self, project_id=None, project_name_with_namespace=None, get_all=False, key=None, per_page=20,
                  page=1):
        params = {'per_page': per_page, 'page': page}
        if get_all:
            params = {'get_all': True, 'per_page': per_page}
        if key:
            params['search'] = key
        tags = self.get_project(
            project_id, project_name_with_namespace).tags.list(**params)
        tags = [{'uid': f"{G_COMMIT[1][0]}:{i.name}", 'name': i.name, 'message': i.message, 'commit': i.commit,
                 'label': G_COMMIT[1][0]} for i in tags]
        return tags

    def list_commits(self, project_id=None, project_name_with_namespace=None, get_all=False, key=None, per_page=20,
                     page=1, ref_name=None, since=None):
        params = {'per_page': per_page, 'page': page}
        if get_all:
            params = {'get_all': True, 'per_page': per_page}
        if key:
            params['search'] = key
        if ref_name:
            params['ref_name'] = ref_name
        if since:
            params['since'] = since
        commits = self.get_project(
            project_id, project_name_with_namespace).commits.list(**params)
        commits = [
            {'title': i.title, 'short_id': i.short_id, 'author_name': i.author_name, 'committer_name': i.committer_name,
             'committed_date': i.committed_date, 'message': i.message, 'web_url': i.web_url} for i in commits]
        return commits

    def repo_checkout(self, repo):
        import subprocess
        git_url = repo.split('//')
        subprocess.call(
            ['git', 'clone', f"{git_url[0]}//oauth2:{self.__token}@{git_url[1]}"])

    def get_user_id(self, username):
        user_list = self.__gl.users.list(username=username)
        if user_list:
            return user_list[0].id
        else:
            return None

    def get_project_from_name(self, project_name):
        projects = self.__gl.projects.list(search=project_name)
        for p in projects:
            if p.name == project_name:
                return p
        return None

    def add_project_member(self, project, user_id, access_level):
        try:
            project.members.create(
                {'user_id': user_id, 'access_level': access_level})
            return True, '成功'
        except Exception as error:
            return False, error

    def del_project_member(self, project, user_id):
        try:
            project.members.delete(user_id)
            return True, '成功'
        except Exception as error:
            return False, error
