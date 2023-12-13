#!/usr/bin/env python
# -*- encoding: utf-8 -*-
'''
@author  :   Charles Lai
@file    :   tasks_build.py
@time    :   2023/03/07 09:39
@contact :   qqing_lai@hotmail.com
@company :   IMAOJIA Co,Ltd
'''

# here put the import lib
import datetime
import json
import re
import time
import copy
import pytz
from ruamel import yaml
from django.core.cache import cache
from django_q.tasks import async_task, result, schedule
from django_q.models import Schedule
from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync
from dbapp.model.model_cmdb import AppInfo, Environment
from common.MailSend import OmsMail
from common.custom_format import convert_xml_to_str_with_pipeline

from common.ext_fun import get_datadict, get_redis_data
from common.utils.JenkinsAPI import GlueJenkins
from common.variables import *
from dbapp.model.model_deploy import BuildJob, BuildJobResult
from dbapp.model.model_ucenter import DataDict

import logging

logger = logging.getLogger('django-q')


def jenkins_log_stage(channel_name, job_id, appinfo_id=0, job_type='app'):
    channel_layer = get_channel_layer()
    JENKINS_CONFIG = get_redis_data('cicd-jenkins')
    jbuild = JenkinsBuild(JENKINS_CONFIG['url'], username=JENKINS_CONFIG['user'],
                          password=JENKINS_CONFIG['password'], job_id=job_id, appinfo_id=appinfo_id, job_type=job_type)
    count = 0
    _flag = True
    while _flag:
        time.sleep(0.5)
        count += 1
        try:
            job_name, job, _ = jbuild.job_info()
            ok, flow_json = jbuild.log_stage()
            if ok:
                _flag = False
            message = flow_json

            if count > 600 and flow_json['status'] == 'NOT_EXECUTED':
                message = {'status': 'NOT_EXEC_TIMEOUT',
                           'stages': [{'logs': '构建超时，请联系运维排查！'}]}
                _flag = False
            if count > 900 and flow_json['status'] == 'IN_PROGRESS':
                message = {'status': 'NOT_EXEC_TIMEOUT',
                           'stages': [{'logs': '构建检测超时，请联系运维排查！'}]}
                _flag = False

            async_to_sync(channel_layer.send)(
                channel_name,
                {
                    "type": "send.message",
                    "message": message
                }
            )
            if count > 600 or _flag is False:
                async_to_sync(channel_layer.send)(
                    channel_name,
                    {
                        "type": "send.message",
                        "message": 'devops-done'
                    }
                )
                break
        except BaseException as e:
            continue


def jenkins_log_console(channel_name, job_id, appinfo_id=0, job_type='app'):
    channel_layer = get_channel_layer()
    JENKINS_CONFIG = get_redis_data('cicd-jenkins')
    jbuild = JenkinsBuild(JENKINS_CONFIG['url'], username=JENKINS_CONFIG['user'],
                          password=JENKINS_CONFIG['password'], job_id=job_id, appinfo_id=appinfo_id, job_type=job_type)
    count = 0
    _flag = True
    while _flag:
        time.sleep(0.1)
        count += 1
        try:
            job_name, job, _ = jbuild.job_info()
            ok, message = jbuild.log_console()
            if ok:
                _flag = False
            async_to_sync(channel_layer.send)(
                channel_name,
                {
                    "type": "send.message",
                    "message": message
                }
            )
            if count > 600 or _flag is False:
                async_to_sync(channel_layer.send)(
                    channel_name,
                    {
                        "type": "send.message",
                        "message": 'devops-done'
                    }
                )
                break
        except BaseException as e:
            continue


def jenkins_callback_handle(*args, **kwargs):
    job_id = kwargs.get('job_id', None)
    appinfo_id = kwargs.get('appinfo_id', None)
    job_type = kwargs.get('job_type', 'app')
    JENKINS_CONFIG = get_redis_data('cicd-jenkins')
    jbuild = JenkinsBuild(JENKINS_CONFIG['url'], username=JENKINS_CONFIG['user'],
                          password=JENKINS_CONFIG['password'], job_id=job_id, appinfo_id=appinfo_id, job_type=job_type)
    jbuild.callback()


def jenkins_job_check(*args, **kwargs):
    job_id = kwargs.get('job_id', None)
    appinfo_id = kwargs.get('appinfo_id', None)
    job_type = kwargs.get('job_type', 'app')
    JENKINS_CONFIG = get_redis_data('cicd-jenkins')
    jbuild = JenkinsBuild(JENKINS_CONFIG['url'], username=JENKINS_CONFIG['user'],
                          password=JENKINS_CONFIG['password'], job_id=job_id, appinfo_id=appinfo_id, job_type=job_type)
    ok, job, _, _ = jbuild.exists()
    if not ok and job_type == 'jar':
        job.status = 4
        job.result = {'status': 'ABORTED',
                      'stages': [{'name': '创建任务', 'status': 'NOT_EXECUTED', 'logs': f'创建任务失败，原因：'}]}
        job.save()


def build_number_binding_hook(task):
    ok, job, job_type = task.result
    if ok:
        # 执行成功
        JENKINS_CONFIG = get_redis_data('cicd-jenkins')
        jbuild = JenkinsBuild(JENKINS_CONFIG['url'], username=JENKINS_CONFIG['user'],
                              password=JENKINS_CONFIG['password'], job_id=job.id, appinfo_id=job.appinfo_id, job_type=job_type)
        jbuild.callback()


def build_number_binding(*args, **kwargs):
    job_id = kwargs.get('job_id', None)
    appinfo_id = kwargs.get('appinfo_id', None)
    job_type = kwargs.get('job_type', 'app')
    queue_number = kwargs.get('queue_number', None)
    try:
        JENKINS_CONFIG = get_redis_data('cicd-jenkins')
        jbuild = JenkinsBuild(JENKINS_CONFIG['url'], username=JENKINS_CONFIG['user'],
                              password=JENKINS_CONFIG['password'], job_id=job_id, appinfo_id=appinfo_id, job_type=job_type)
        ok, job, _ = jbuild.job_info()
        if ok and job:
            if job.build_number == 0:
                ok, build_number = jbuild.queue(queue_number)
                if ok and build_number:  # and job_type == 'app':
                    job.build_number = build_number
                    job.save()
                    return True, job, job_type
    except BaseException as e:
        pass
    return False, None, None


class JenkinsBuild(object):
    JOB_MODEL = {'app': BuildJob}

    def __init__(self, url, username, password, job_id=0, appinfo_id=0, job_type='app'):
        self.__url = url
        self.__username = username
        self.__password = password
        self.__job_id = job_id
        self.__appinfo_id = int(appinfo_id) if appinfo_id else 0
        self.__job_type = job_type
        self.jenkins_cli = GlueJenkins(
            self.__url, self.__username, self.__password)

    def job_info(self):
        try:
            job = self.JOB_MODEL[self.__job_type].objects.filter(
                pk=self.__job_id).first()
            if self.__appinfo_id != 0:
                appinfo_obj = AppInfo.objects.get(id=self.__appinfo_id)
                job_name = appinfo_obj.jenkins_jobname
                return job_name, job, appinfo_obj
            job_name = f'jar-dependency-deploy-job-{job.name}'
            return job_name, job, None
        except BaseException as e:
            return None, None, None

    def log_stage(self):
        job_name, job, _ = self.job_info()
        try:
            flow_json = self.jenkins_cli.get_flow_detail(
                job_name, build_number=job.build_number)
            flow_json['data'] = {'job_id': 0}
        except BaseException as e:
            pass
        r = {'SUCCESS': 1, 'FAILED': 2, 'ABORTED': 4, 'FAILURE': 2}
        if flow_json['status'] in r:
            # 当前状态不在 {'IN_PROGRESS': 3, 'NOT_EXECUTED': 5}
            return True, flow_json
        return False, flow_json

    def log_console(self):
        job_name, job, _ = self.job_info()
        try:
            flow_json = self.jenkins_cli.get_build_console_output(
                job_name, number=job.build_number)
        except BaseException as e:
            pass
        flow_info = self.jenkins_cli.get_build_info(job_name, job.build_number)
        if flow_info['result']:
            return True, {'status': flow_info['result'], 'data': flow_json}
        return False, {'status': flow_info['result'], 'data': flow_json}

    def queue(self, queue_number):
        count = 0
        _flag = True
        while _flag:
            queue_item = self.jenkins_cli.get_queue_item(queue_number)
            if 'executable' in queue_item:
                if queue_item['executable'].get('number', None):
                    return True, queue_item['executable']['number']
            count += 1
            if count > 600:
                _flag = False
            time.sleep(0.5)
        return False, 0

    def create(self, jenkinsfile='jardependency/Jenkinsfile', desc='Jar依赖包构建上传任务'):
        JENKINS_CONFIG = get_redis_data('cicd-jenkins')
        job_name, _, appinfo_obj = self.job_info()
        try:
            config_xml = convert_xml_to_str_with_pipeline(JENKINS_CONFIG['xml'],
                                                          JENKINS_CONFIG['pipeline']['http_url_to_repo'],
                                                          JENKINS_CONFIG['gitlab_credit'],
                                                          desc,
                                                          jenkinsfile,
                                                          scm=True)
            if not self.jenkins_cli.job_exists(job_name):
                self.jenkins_cli.create_job(
                    name=job_name, config_xml=config_xml)
            else:
                self.jenkins_cli.reconfig_job(
                    name=job_name, config_xml=config_xml)
            return True, None
        except Exception as err:
            logger.exception(f'创建Jenkins任务[{job_name}]失败, 原因: {err}')
            return False, f'创建Jenkins任务[{job_name}]失败, 原因: {err}'

    def build(self, params):
        job_name, job, _ = self.job_info()
        try:
            if self.jenkins_cli.get_job_info(job_name).get('inQueue'):
                logger.info(f'构建失败, 原因: Jenkins job 排队中 请稍后再试')
                return False, 'Jenkins job 排队中 请稍后再试'
        except Exception as err:
            logger.error(f'获取构建的Jenkins任务[{job_name}]失败, 原因: {err}')
            return False, '获取Jenkins JOB失败，可能job不存在或者jenkins未运行，联系运维检查！'
        try:
            queue_number = self.jenkins_cli.build_job(
                job_name, parameters=params)
            if queue_number:
                return True, queue_number, job
            return False, None, 'Jenkins任务异常.'
        except BaseException as e:
            logger.exception(f'构建异常，原因：{e}')
            return False, None, f'构建异常，原因：{e}'

    def exists(self):
        job_name, job, appinfo_obj = self.job_info()
        return self.jenkins_cli.job_exists(job_name), job, appinfo_obj

    def create_view(self, appinfo_obj: AppInfo, env: Environment):
        view_xml_config = f'''<?xml version="1.0" encoding="UTF-8"?>
<hudson.model.ListView>
  <name>{appinfo_obj.app.project.alias}{env.alias}</name>
  <filterExecutors>false</filterExecutors>
  <filterQueue>false</filterQueue>
  <properties class="hudson.model.View$PropertyList"/>
  <jobNames>
    <comparator class="hudson.util.CaseInsensitiveComparator"/>
  </jobNames>
  <jobFilters/>
  <columns>
    <hudson.views.StatusColumn/>
    <hudson.views.WeatherColumn/>
    <hudson.views.JobColumn/>
    <jenkins.branch.DescriptionColumn/>
    <hudson.views.LastSuccessColumn/>
    <hudson.views.LastFailureColumn/>
    <hudson.views.LastDurationColumn/>
    <hudson.views.BuildButtonColumn/>
  </columns>
  <includeRegex>{env.name.lower()}-.*-{appinfo_obj.app.project.name.lower()}-.*</includeRegex>
</hudson.model.ListView>'''
        self.jenkins_cli.create_view(
            f'{appinfo_obj.app.project.alias}{env.alias}', view_xml_config)

    def callback(self):
        """
        Jenkins Pipeline构建结束回调平台，平台再获取构建结果入库
        :param appinfo_id: 应用模块ID
        :param build_number: 构建ID
        :return:
        """
        job_name, job, appinfo_obj = self.job_info()
        if not job:
            return
        # 标记回调
        cache.set(f'{JENKINS_CALLBACK_KEY}{job.id}', 1, 60 * 60)
        time.sleep(1)
        flow_json = self.jenkins_cli.get_flow_detail(
            job_name, build_number=job.build_number)
        flow_console_output = self.jenkins_cli.get_build_console_output(
            job_name, number=job.build_number)
        if JENKINS_STATUS_MAP[flow_json['status']] == 3:
            # Jenkins构建成功后回调平台，等待平台响应，此时状态仍为3时，需要重新查询
            # 构建中再次查询
            async_task('qtasks.tasks_build.jenkins_callback_handle', **
                       {'job_id': int(job.id), 'appinfo_id': appinfo_obj.id if appinfo_obj else 0, 'job_type': self.__job_type})
            return

        job.status = JENKINS_STATUS_MAP[flow_json['status']]
        job.save()

        if self.__job_type == 'app':
            # 应用构建
            if flow_json['status'] == 'SUCCESS' and appinfo_obj.environment.image_sync:
                try:
                    # 当前构建结果成功, 可用镜像存入缓存
                    _key = f"{DEPLOY_IMAGE_KEY}{appinfo_obj.app.id}"
                    if appinfo_obj.app.multiple_ids:
                        # 存在关联应用
                        _key = f"{DEPLOY_IMAGE_KEY}{'+'.join([str(i) for i in sorted(appinfo_obj.app.multiple_ids)])}"
                    jobs = cache.get(_key, [])
                    _job_retain = int(get_datadict('JOB_RETAIN')['value']) if get_datadict(
                        'JOB_RETAIN') else 10
                    if len(jobs) > _job_retain:
                        jobs.pop()
                    jobs.insert(0, job)
                    # 缓存不过期
                    cache.set(_key, jobs, 60 * 60 * 24 * 3)
                    cache.set(f"{_key}:{CI_LATEST_SUCCESS_KEY}",
                              job, 60 * 60 * 24 * 3)
                except BaseException as e:
                    logger.exception(
                        f"应用[{appinfo_obj.uniq_tag}]构建缓存异常, 原因: {e}")
            # 缓存最新构建记录
            try:
                cache.set(f"{CI_LATEST_KEY}{appinfo_obj.id}",
                          job, 60 * 60 * 24 * 3)
            except BaseException as e:
                logger.exception('缓存最新构建异常', e)
            # 存储结果
            BuildJobResult.objects.create(
                **{'job_id': job.id, 'result': json.dumps(flow_json), 'console_output': flow_console_output})
            cache.set(f"{CI_RESULT_KEY}{job.id}",
                      {'result': json.dumps(
                          flow_json), 'console_output': flow_console_output},
                      60 * 5)
            # 构建完成通知
            self.notice(job, appinfo_obj, flow_json)
            return
        job.result = json.dumps(flow_json)
        job.console_output = flow_console_output
        job.save()

    def notice(self, job, appinfo_obj, flow_json):
        try:
            # 构建完成通知
            notify = appinfo_obj.app.project.notify
            if notify.get('mail', None) is None and notify.get('robot', None) is None:
                logger.info(f"应用[{appinfo_obj.uniq_tag}]未启用消息通知.")
                return
            # 通知消息key
            msg_key = f"{MSG_KEY}{appinfo_obj.environment.name}:{appinfo_obj.app.appid}:{job.build_number}"
            # 延时通知
            delay = 0.1
            title = f"{appinfo_obj.app.appid}构建{flow_json['status']}"
            try:
                git_commit_date = datetime.datetime.strptime(job.commits['committed_date'],
                                                             "%Y-%m-%dT%H:%M:%S.%f+00:00").replace(
                    tzinfo=datetime.timezone.utc).astimezone(pytz.timezone('Asia/Shanghai'))
            except:
                git_commit_date = job.commits['committed_date']
            msg = f'''**<font color="{JENKINS_COLOR_MAP[flow_json['status']]}">{DataDict.objects.get(key=appinfo_obj.app.category).value} 构建 {flow_json['status']}</font>**    
项目: {appinfo_obj.app.project.alias}    
环境:  {appinfo_obj.environment.name}  
应用ID：  {appinfo_obj.app.appid}  
构建NO.：  [{job.build_number}]  
{'构建分支模块' if appinfo_obj.app.category == 'category.front' else '构建分支'}：  {job.commit_tag['label']}/{job.commit_tag['name']} {appinfo_obj.app.category == 'category.front' and job.modules}   
提交ID：  {job.commits['short_id']}  
提交人：  {job.commits['committer_name']}     
提交信息：  {job.commits['message']}  
提交时间：  {git_commit_date}  
构建类型: {'构建发布' if job.is_deploy else '构建'}    
构建者: {job.deployer.first_name or job.deployer.username}    
构建时间: {job.created_time.astimezone(pytz.timezone('Asia/Shanghai')).strftime('%Y-%m-%d %H:%M:%S+08:00')}  
    '''
            if job.is_deploy:
                delay = get_datadict('NOTIFY_DELAY', 1)['delay'] if get_datadict(
                    'NOTIFY_DELAY', 1) else 60 * 5
            if job.status != 1:
                # 构建结果不成功立即发出通知
                delay = 0.1
            if notify.get('mail', None):
                try:
                    mail_send = OmsMail()
                    recv_mail = job.deployer.email
                    mail_send.deploy_notify(title, msg, recv_mail)
                except BaseException as e:
                    logger.warning(f"邮件发送失败, 原因: {e}")
            # 机器人通知
            if notify.get('robot', None):
                try:
                    robot = notify['robot']
                    recv_phone = job.deployer.mobile
                    recv_openid = job.deployer.feishu_openid
                    cache.set(f"{msg_key}:ci:{job.id}",
                              {'appid': appinfo_obj.app.appid, 'robot': robot, 'recv_phone': recv_phone,
                               'recv_openid': recv_openid, 'msg_key': msg_key,
                               'msg': msg,
                               'title': title}, 60 * 60 * 3)
                    cache.set(f"{DELAY_NOTIFY_KEY}{msg_key}", {'curr_time': datetime.datetime.now(), 'delay': delay},
                              60 * 60 * 3)
                    taskid = schedule('qtasks.tasks.deploy_notify_queue', *[msg_key],
                                      **{'appid': appinfo_obj.app.appid, 'robot': robot,
                                         'recv_phone': recv_phone, 'recv_openid': recv_openid,
                                         'msg_key': msg_key, 'title': title},
                                      schedule_type=Schedule.ONCE,
                                      next_run=datetime.datetime.now() + datetime.timedelta(seconds=delay))
                except BaseException as e:
                    logger.warning(f"机器人通知发送失败, 原因: {e}")
        except BaseException as e:
            pass
