#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
@Author : Charles Lai
@Contact : qqing_lai@hotmail.com
@Time : 2020/9/29 下午3:15
@FileName: JenkinsAPI.py
@Blog ：https://imaojia.com
"""

import jenkins
import shortuuid
import time
import os
import json
from django.conf import settings
import tempfile
import requests
from jenkins import Jenkins, JenkinsException, req_exc, NotFoundException
from six.moves.urllib.parse import quote, urljoin, unquote
import xml.etree.ElementTree as ET
import xmltodict

import logging

logger = logging.getLogger('drf')


STAGE_INFO = '%(folder_url)sjob/%(short_name)s/%(number)d/wfapi/describe'
STAGE_LOG = '%(folder_url)sjob/%(short_name)s/%(number)d/execution/node/%(node_number)d/wfapi/log'
STAGE_DES = "%(folder_url)sjob/%(short_name)s/%(number)d/execution/node/%(node_number)d/wfapi/describe"
STAGE_BLUE = "%(folder_url)sblue/rest/organizations/jenkins/pipelines/%(short_name)s/runs/%(number)d/nodes/%(node_number)d/steps/"
CREATE_JOB = '%(folder_url)screateItem?name=%(short_name)s'
CONFIG_JOB = '%(folder_url)sjob/%(short_name)s/config.xml'
DEFAULT_HEADERS = {'Content-Type': 'text/xml; charset=utf-8'}
SET_JOB_BUILD_NUMBER = '%(folder_url)sjob/%(short_name)s/nextbuildnumber/submit'
CREATE_CREDENTIAL_GLOBAL = 'credentials/store/system/domain/_/createCredentials'
CONFIG_CREDENTIAL_GLOBAL = 'credentials/store/system/domain/_/credential/%(name)s/config.xml'
CREDENTIAL_INFO_GLOBAL = 'credentials/store/system/domain/_/credential/%(name)s/api/json?depth=0'
STAGE_BLUE_LOG = "%(links)s"
VIEW_NAME = '%(folder_url)sview/%(short_name)s/api/json?tree=name'
VIEW_JOBS = 'view/%(name)s/api/json?tree=jobs[url,color,name]'
CREATE_VIEW = '%(folder_url)screateView?name=%(short_name)s'
CONFIG_VIEW = '%(folder_url)sview/%(short_name)s/config.xml'
DELETE_VIEW = '%(folder_url)sview/%(short_name)s/doDelete'
JOB_INFO = '%(folder_url)sjob/%(short_name)s/api/json?depth=%(depth)s'
Q_ITEM = 'queue/item/%(number)d/api/json?depth=%(depth)s'


class EmptyResponseException(JenkinsException):
    '''A special exception to call out the case receiving an empty response.'''
    pass


class GlueJenkins(Jenkins):

    def __init__(self, url=None, username=None, password=None):
        self.__url = url
        self.__username = username
        self.__password = password
        super(GlueJenkins, self).__init__(
            self.__url, self.__username, self.__password)

    def _get_encoded_params(self, params):
        for k, v in params.items():
            if k in ["name", "msg", "short_name", "from_short_name",
                     "to_short_name", "folder_url", "from_folder_url", "to_folder_url"]:
                params[k] = quote(v.encode('utf8'))
        return params

    def _build_url(self, format_spec, variables=None):

        if variables:
            url_path = format_spec % self._get_encoded_params(variables)
        else:
            url_path = format_spec
        return str(urljoin(self.server, url_path))

    def assert_credential_exists(self, name, folder_name=None, domain_name='_',
                                 exception_message='credential[%s] does not exist.'):
        '''Raise an exception if credential does not exist in domain of folder

        :param name: Name of credential, ``str``
        :param folder_name: Folder name, ``str``
        :param domain_name: Domain name, default is '_', ``str``
        :param exception_message: Message to use for the exception.
                                  Formatted with ``name``, ``domain_name``,
                                  and ``folder_name``
        :throws: :class:`JenkinsException` whenever the credentail
            does not exist in domain of folder
        '''
        if not self.credential_exists(name, folder_name, domain_name):
            raise JenkinsException(exception_message
                                   % name)

    def get_credential_global_config(self, name, domain_name='_'):
        '''Get configuration of credential in domain of folder.
        :param name: Name of credentail, ``str``
        :param domain_name: Domain name, default is '_', ``str``
        :returns: Credential configuration (XML format)
        '''
        return self.jenkins_open(requests.Request(
            'GET', self._build_url(CONFIG_CREDENTIAL_GLOBAL, locals())
        ))

    def get_credential_info(self, name, folder_name=None, domain_name='_'):
        '''Get credential information dictionary in domain of folder

        :param name: Name of credentail, ``str``
        :param folder_name: folder_name, ``str``
        :param domain_name: Domain name, default is '_', ``str``
        :returns: Dictionary of credential info, ``dict``
        '''
        try:
            response = self.jenkins_open(requests.Request(
                'GET', self._build_url(CREDENTIAL_INFO_GLOBAL, locals())
            ))
            if response:
                return json.loads(response)
            else:
                raise JenkinsException('credential[%s] does not exist.' % name)
        except (req_exc.HTTPError, NotFoundException):
            raise JenkinsException('credential[%s] does not exist.' % name)
        except ValueError:
            raise JenkinsException(
                'Could not parse JSON info for credential[%s].' % name
            )

    def credential_exists(self, name, folder_name=None, domain_name='_'):
        '''Check whether a credentail exists in domain of folder

        :param name: Name of credentail, ``str``
        :param folder_name: Folder name, ``str``
        :param domain_name: Domain name, default is '_', ``str``
        :returns: ``True`` if credentail exists, ``False`` otherwise
        '''
        try:
            return self.get_credential_info(name)['id'] == name
        except JenkinsException:
            return False

    def create_credential_global(self, name=None, user=None, password=None, secret=None, comment=None, domain_name='_'):
        '''Create credentail in domain of folder

        :param name: username
        :param password: password
        :param comment: comment, ``str``
        :param config_xml: New XML configuration, ``str``
        :param domain_name: Domain name, default is '_', ``str``
        '''
        st = shortuuid.ShortUUID()
        st.set_alphabet(
            f"0123456789{''.join([chr(i) for i in range(ord('a'), ord('z') + 1)])}")
        if name is None:
            name = '-'.join(['api', st.random(length=8),
                            st.random(length=4), st.random(length=12)])
        config_xml = '''<com.cloudbees.plugins.credentials.impl.UsernamePasswordCredentialsImpl>
  <scope>GLOBAL</scope>
  <id>%s</id>
  <description>[%s] Created by DevOps Platform</description>
  <username>%s</username>
  <password>%s</password>
</com.cloudbees.plugins.credentials.impl.UsernamePasswordCredentialsImpl>''' % (name, comment, user, password)
        if user is None:
            config_xml = '''<org.jenkinsci.plugins.plaincredentials.impl.StringCredentialsImpl>
  <scope>GLOBAL</scope>
  <id>%s</id>
  <description>[%s] Created by DevOps Platform</description>
  <secret>%s</secret>
</org.jenkinsci.plugins.plaincredentials.impl.StringCredentialsImpl>''' % (name, comment, secret)
        if self.credential_exists(name):
            raise JenkinsException('credential[%s] already exists.' % name)

        self.jenkins_open(requests.Request(
            'POST', self._build_url(CREATE_CREDENTIAL_GLOBAL, locals()),
            data=config_xml.encode('utf-8'),
            headers=DEFAULT_HEADERS
        ))
        self.assert_credential_exists(
            name, exception_message='create credential[%s] failed.')
        return {'status': 0, 'data': name}

    def reconfig_credential_global(self, name, user=None, password=None, secret=None, comment=None, domain_name='_'):
        """
        Reconfig credential with new config in domain of folder
        :param name: name, ``str``
        :param user:
        :param password:
        :param secret:
        :param comment:
        :param domain_name: Domain name, default is '_', ``str``
        :return:
        """
        reconfig_url = self._build_url(CONFIG_CREDENTIAL_GLOBAL, locals())
        config_xml = self.get_credential_global_config(name)
        xml_dict = xmltodict.parse(config_xml)
        if user is None:
            xml_dict['org.jenkinsci.plugins.plaincredentials.impl.StringCredentialsImpl']['secret'] = secret
            if comment:
                xml_dict['org.jenkinsci.plugins.plaincredentials.impl.StringCredentialsImpl']['description'] = comment
        else:
            xml_dict['com.cloudbees.plugins.credentials.impl.UsernamePasswordCredentialsImpl']['username'] = user
            xml_dict['com.cloudbees.plugins.credentials.impl.UsernamePasswordCredentialsImpl']['password'] = password
            if comment:
                xml_dict['com.cloudbees.plugins.credentials.impl.UsernamePasswordCredentialsImpl'][
                    'description'] = comment
        config_xml = xmltodict.unparse(xml_dict, pretty=True)
        self.jenkins_open(requests.Request(
            'POST', reconfig_url,
            data=config_xml.encode('utf-8'),
            headers=DEFAULT_HEADERS
        ))

    def create_job(self, name, config_xml):
        '''Create a new Jenkins job

        :param name: Name of Jenkins job, ``str``
        :param config_xml: config file text, ``str``
        '''
        folder_url, short_name = self._get_job_folder(name)
        if self.job_exists(name):
            raise JenkinsException('job[%s] already exists' % (name))

        try:
            self.jenkins_open(requests.Request(
                'POST', self._build_url(CREATE_JOB, locals()),
                data=config_xml.encode('utf-8'),
                headers=DEFAULT_HEADERS
            ))
        except NotFoundException:
            raise JenkinsException('Cannot create job[%s] because folder '
                                   'for the job does not exist' % (name))
        self.assert_job_exists(name, 'create[%s] failed')

    def reconfig_job(self, name, config_xml):
        '''Change configuration of existing Jenkins job.

        To create a new job, see :meth:`Jenkins.create_job`.

        :param name: Name of Jenkins job, ``str``
        :param config_xml: New XML configuration, ``str``
        '''
        folder_url, short_name = self._get_job_folder(name)
        reconfig_url = self._build_url(CONFIG_JOB, locals())
        self.jenkins_open(requests.Request(
            'POST', reconfig_url,
            data=config_xml.encode('utf-8'),
            headers=DEFAULT_HEADERS
        ))

    def get_stage_describe(self, name, number, node_number):
        """ 获取 单个stage 详情 """
        folder_url, short_name = self._get_job_folder(name)
        try:
            response = self.jenkins_open(requests.Request(
                'GET', self._build_url(STAGE_DES, locals())
            ))

            if response:
                return json.loads(response)
            else:
                raise JenkinsException('job[%s] number[%d] does not exist'
                                       % (name, number))
        except (req_exc.HTTPError, NotFoundException):
            raise JenkinsException('job[%s] number[%d] does not exist'
                                   % (name, number))
        except ValueError:
            raise JenkinsException(
                'Could not parse JSON info for job[%s] number[%d]'
                % (name, number)
            )

    def get_stage_logs(self, name, number, node_number):
        """ 获取 stage 执行日志"""
        folder_url, short_name = self._get_job_folder(name)
        try:
            response = self.jenkins_open(requests.Request(
                'GET', self._build_url(STAGE_LOG, locals())
            ))
            if response:
                return json.loads(response)
            else:
                raise JenkinsException('job[%s] number[%d] does not exist'
                                       % (name, number))
        except (req_exc.HTTPError, NotFoundException):
            raise JenkinsException('job[%s] number[%d] does not exist'
                                   % (name, number))
        except ValueError:
            raise JenkinsException(
                'Could not parse JSON info for job[%s] number[%d]'
                % (name, number)
            )

    def get_stage_info(self, name, number, depth=0):

        folder_url, short_name = self._get_job_folder(name)
        try:
            response = self.jenkins_open(requests.Request(
                'GET', self._build_url(STAGE_INFO, locals())
            ))
            if response:
                return json.loads(response)
            else:
                raise JenkinsException('job[%s] number[%d] does not exist'
                                       % (name, number))
        except (req_exc.HTTPError, NotFoundException):
            raise JenkinsException('job[%s] number[%d] does not exist'
                                   % (name, number))
        except ValueError:
            raise JenkinsException(
                'Could not parse JSON info for job[%s] number[%d]'
                % (name, number)
            )

    def get_flow_detail(self, job_name, build_number):
        stage_data = self.get_stage_info(name=job_name, number=build_number)
        stages = stage_data.get('stages')
        for i in stages:
            logs = ''
            try:
                # 获取stage返回信息
                response = self.jenkins_open(requests.Request(
                    'GET', self._build_url(
                        unquote(i['_links']['self']['href']), locals())
                ))
                if response:
                    res = json.loads(response)
                    for j in res['stageFlowNodes']:
                        response = self.jenkins_open(requests.Request(
                            'GET', self._build_url(
                                unquote(j['_links']['log']['href']), locals())
                        ))
                        res = json.loads(response)
                        try:
                            # 移除href html信息，保留链接文字
                            import re
                            pat = re.compile('<a href[^>]*>')
                            logs = logs + '\n' + \
                                pat.sub('', res['text'].replace('</a>', ''))
                        except:
                            pass
                else:
                    raise JenkinsException('job[%s] number[%d] does not exist'
                                           % (job_name, build_number))
            except (req_exc.HTTPError, NotFoundException):
                raise JenkinsException('job[%s] number[%d] does not exist'
                                       % (job_name, build_number))
            except ValueError:
                raise JenkinsException(
                    'Could not parse JSON info for job[%s] number[%d]'
                    % (job_name, build_number)
                )

            stage_data["stages"][stages.index(i)]['logs'] = logs
        return stage_data

    def get_queue_item(self, number, depth=0):
        '''Get information about a queued item (to-be-created job).

        The returned dict will have a "why" key if the queued item is still
        waiting for an executor.

        The returned dict will have an "executable" key if the queued item is
        running on an executor, or has completed running. Use this to
        determine the job number / URL.

        :param name: queue number, ``int``
        :returns: dictionary of queued information, ``dict``
        '''
        url = self._build_url(Q_ITEM, locals())
        try:
            response = self.jenkins_open(requests.Request('GET', url))
            if response:
                return json.loads(response)
            else:
                raise JenkinsException('queue number[%d] does not exist'
                                       % number)
        except (req_exc.HTTPError, NotFoundException):
            raise JenkinsException('queue number[%d] does not exist' % number)
        except ValueError:
            raise JenkinsException(
                'Could not parse JSON info for queue number[%d]' % number
            )

    def build_job(self, name, parameters=None, token=None):
        '''Trigger build job.

        This method returns a queue item number that you can pass to
        :meth:`Jenkins.get_queue_item`. Note that this queue number is only
        valid for about five minutes after the job completes, so you should
        get/poll the queue information as soon as possible to determine the
        job's URL.

        :param name: name of job
        :param parameters: parameters for job, or ``None``, ``dict``
        :param token: Jenkins API token
        :returns: ``int`` queue item
        '''
        response = self.jenkins_request(requests.Request(
            'POST', self.build_job_url(name, parameters, token)))

        if 'Location' not in response.headers:
            raise EmptyResponseException(
                "Header 'Location' not found in "
                "response from server[%s]" % self.server)

        location = response.headers['Location']
        if location.endswith('/'):
            location = location[:-1]
        parts = location.split('/')
        number = int(parts[-1])
        return number

    def get_job_config(self, name):
        '''Get configuration of existing Jenkins job.

        :param name: Name of Jenkins job, ``str``
        :returns: job configuration (XML format)
        '''
        folder_url, short_name = self._get_job_folder(name)
        request = requests.Request(
            'GET', self._build_url(CONFIG_JOB, locals()))
        return self.jenkins_open(request)

    def get_job_info(self, name, depth=0, fetch_all_builds=False):
        '''Get job information dictionary.

        :param name: Job name, ``str``
        :param depth: JSON depth, ``int``
        :param fetch_all_builds: If true, all builds will be retrieved
                                 from Jenkins. Otherwise, Jenkins will
                                 only return the most recent 100
                                 builds. This comes at the expense of
                                 an additional API call which may
                                 return significant amounts of
                                 data. ``bool``
        :returns: dictionary of job information
        '''
        folder_url, short_name = self._get_job_folder(name)
        try:
            response = self.jenkins_open(requests.Request(
                'GET', self._build_url(JOB_INFO, locals())
            ))
            if response:
                if fetch_all_builds:
                    return self._add_missing_builds(json.loads(response))
                else:
                    return json.loads(response)
            else:
                raise JenkinsException('job[%s] does not exist' % name)
        except (req_exc.HTTPError, NotFoundException):
            raise JenkinsException('job[%s] does not exist' % name)
        except ValueError:
            raise JenkinsException(
                "Could not parse JSON info for job[%s]" % name)
