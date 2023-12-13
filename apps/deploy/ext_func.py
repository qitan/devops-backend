import base64
import datetime
import os
import time
from django.core.cache import cache
from django.db.models import Q
from django.db import transaction
from django_q.tasks import async_task, schedule
from django_q.models import Schedule
from common.custom_format import convert_xml_to_str_with_pipeline
from common.utils.AesCipher import AesCipher
from common.variables import CI_LATEST_KEY
from deploy.documents import BuildJobDocument, DeployJobDocument
from deploy.serializers import BuildJobListSerializer, DeployJobSerializer
from deploy.rds_transfer import rds_transfer_es
from qtasks.tasks_build import JenkinsBuild
from dbapp.models import AppInfo
from dbapp.model.model_cmdb import DevLanguage, KubernetesDeploy
from common.ext_fun import get_datadict, get_redis_data, harbor_cli, template_generate
from config import PLAYBOOK_PATH
from dbapp.model.model_deploy import BuildJob, DeployJob, PublishOrder
from dbapp.model.model_ucenter import DataDict, UserProfile
import logging

from dbapp.model.model_workflow import Workflow

logger = logging.getLogger(__name__)


@transaction.atomic
def app_build_handle(request_data, appinfo_obj: AppInfo, user: UserProfile):
    """
    应用构建
    """
    cipher = AesCipher('sdevops-platform')
    commit_tag = request_data.get('commit_tag', None)
    commits = request_data.get('commits', '')
    modules = request_data.get('modules', 'dist')
    custom_tag = request_data.get('custom_tag', None)
    # {0: 构建, 1: 构建发布}
    is_deploy = request_data.get('is_deploy', False)

    language = DevLanguage.objects.get(name=appinfo_obj.app.language)

    OPS_URL = get_redis_data('platform')['url']
    jenkins = get_redis_data('cicd-jenkins')
    category = appinfo_obj.app.category
    namespace = appinfo_obj.namespace
    job_name = appinfo_obj.jenkins_jobname

    forward = 'no'
    opshost = ''

    # 定义harbor空配置
    harbor_config = {}
    build_time = datetime.datetime.now().strftime('%Y%m%d%H%M%S')
    JENKINS_CONFIG = get_redis_data('cicd-jenkins')
    jbuild = JenkinsBuild(JENKINS_CONFIG['url'], username=JENKINS_CONFIG['user'],
                          password=JENKINS_CONFIG['password'])
    try:
        if not jbuild.jenkins_cli.job_exists(job_name):
            # 应用模块已启用jenkins但找不到jenkins任务时自动创建
            jbuild.jenkins_cli.create_job(name=job_name,
                                          config_xml=convert_xml_to_str_with_pipeline(jenkins['xml'],
                                                                                      jenkins['pipeline']['http_url_to_repo'],
                                                                                      jenkins['gitlab_credit'],
                                                                                      appinfo_obj.app.alias,
                                                                                      f'{appinfo_obj.app.language}/Jenkinsfile'))
        if jbuild.jenkins_cli.get_job_info(job_name).get('inQueue'):
            logger.info(
                f'应用[{appinfo_obj.uniq_tag}]构建失败, 原因: Jenkins job 排队中 请稍后再试')
            return False, f"Jenkins job 排队中 请稍后再试"
    except Exception as err:
        logger.error(
            f'获取应用[{appinfo_obj.uniq_tag}]的Jenkins任务[{job_name}]失败, 原因: {err}')
        return False, "获取Jenkins JOB失败，可能job不存在或者jenkins未运行，联系运维检查"

    init_point = transaction.savepoint()

    try:
        build_number = jbuild.jenkins_cli.get_job_info(job_name)[
            'nextBuildNumber']
        image_name = f"{namespace}/{appinfo_obj.app.name.replace('.', '-')}"
        image_tag = f"{build_number}_{build_time}_{commits['short_id']}"
        if custom_tag:
            image_tag = custom_tag

        # 从绑定的第一个k8s中获取idc运维中转机器
        if appinfo_obj.app.category.split('.')[-1] == 'server' and appinfo_obj.app.is_k8s == 'k8s':
            k8s = appinfo_obj.kubernetes.first()
            if k8s is None:
                logger.error(f'创建任务失败, 原因: 应用未关联Kubernetes!')
                return False, f"应用未关联Kubernetes!"
            try:
                if k8s.idc:
                    ok, harbor_config = harbor_cli(
                        namespace, **{'id': k8s.idc.repo})
                    if not ok:
                        return False, harbor_config

                    if k8s.idc.forward:
                        forward = 'yes'
                        if not k8s.idc.ops:
                            logger.error(
                                f'创建任务失败, 原因: 应用所在IDC[{k8s.idc.name}]未配置中转运维机器!')
                            return False, f"应用所在IDC[{k8s.idc.name}]未配置中转运维机器!"
                        opshost = k8s.idc.ops
                else:
                    logger.exception(
                        f'创建任务失败, 原因: 应用所在Kubernetes[{k8s.name}]未关联IDC!')
                    return False, f"应用所在Kubernetes[{k8s.name}]未关联IDC!"
            except BaseException as err:
                logger.exception(
                    f'获取应用[{appinfo_obj.uniq_tag}]中转机器[{job_name}]失败, 原因: {err}')
                return False, f"创建构建任务失败, ERROR: {err}"
        else:
            # 非Kubernetes部署的后端应用
            if appinfo_obj.app.category.split('.')[-1] == 'server':
                ok, harbor_config = harbor_cli(
                    namespace, **{'id': k8s.idc.repo})
                if not ok:
                    return False, harbor_config
            else:
                # TODO: 同步静态文件是否区分需要中转
                forward = 'yes'
                try:
                    opshost = DataDict.objects.get(key='REMOTE_HOSTS').value
                except BaseException as e:
                    logger.exception(
                        f'创建任务失败, 原因: 未配置中转机器, 请检查数据字典[REMOTE_HOSTS]是否存在!')
                    return False, "未配置中转机器, 请检查数据字典[REMOTE_HOSTS]是否存在!"

        # {0: 未构建, 1: 构建成功, 2: 构建失败, 3: 构建中, 4: 作废}
        build_image = f'{image_name}:{image_tag}'
        if category == 'category.front':
            # 前端
            build_image += f'_{modules.split(":")[-1]}'  # .replace("_", "-")}'
        data = {
            "deployer": user.id,
            "status": 3,
            'appinfo_id': appinfo_obj.id,
            'appid': appinfo_obj.app.appid,
            'build_number': build_number,
            'is_deploy': 1 if is_deploy else 0,
            'commits': commits,
            'commit_tag': commit_tag,
            'image': build_image,
            'batch_uuid': request_data.get('batch_uuid', None),
            'modules': f'{modules.split(":")[-1]}' if category == 'category.front' else ''
        }
        serializer = BuildJobListSerializer(data=data)
        if not serializer.is_valid(raise_exception=False):
            return False, f"创建构建任务失败"
        serializer.save()
        data = serializer.data
        job = BuildJob.objects.get(id=data['id'])
        JENKINS_CONFIG = get_redis_data('cicd-jenkins')
        jbuild = JenkinsBuild(JENKINS_CONFIG['url'], username=JENKINS_CONFIG['user'],
                              password=JENKINS_CONFIG['password'], job_id=data['id'], appinfo_id=appinfo_obj.id, job_type='app')
        ok, _, _, = jbuild.exists()
        if not ok:
            # Jenkins任务不存在，重新创建
            jbuild.create(
                jenkinsfile=f'{appinfo_obj.app.language}/Jenkinsfile', desc=appinfo_obj.app.alias)
        try:
            harbor_config.pop('user', None)
            harbor_config.pop('password', None)
            harbor_config.pop('public', None)
            params = {
                'deploy_env': appinfo_obj.environment.name,
                'command': 1,
                'config': {'appinfo_id': appinfo_obj.id, 'appid': appinfo_obj.app.appid.replace('.', '-'),
                           'app_name': appinfo_obj.app.name,
                           'target': appinfo_obj.app.target.get('value', 'default'),
                           'modules_name': modules and modules.split(":")[0] or '',
                           'modules_output': modules and modules.split(":")[-1] or '',
                           'dockerfile': base64.encodebytes(
                    appinfo_obj.app.dockerfile.get('value', 'default').encode('utf-8')).decode('utf-8'),
                    'deploy_env': appinfo_obj.environment.name, 'is_deploy': 'cd' if is_deploy else 'ci',
                    'build_command': appinfo_obj.build_command or '',
                    'language': language.name,
                    'base_image': f"{language.base_image['image']}:{language.base_image['tag']}",
                    'commit_label': commit_tag['label'], 'commit_name': commit_tag['name'],
                    'commit_id': commits['short_id'],
                    'category': appinfo_obj.app.category, 'namespace': namespace,
                    'repo_url': appinfo_obj.app.repo['http_url_to_repo'],
                    'harbor_config': harbor_config, 'image': {'name': image_name, 'tag': image_tag},
                    'credentials_id': jenkins['gitlab_credit'],
                    'job_build_time': build_time, 'pipeline_url': jenkins['pipeline']['http_url_to_repo'],
                    'platform_credit': jenkins['platform_credit'],
                    'platform_secret': cipher.encrypt(
                    get_redis_data(jenkins['platform_secret'])['token']),
                    'forward': forward, 'opshost': opshost,
                    'jobid': data['id'],
                    'ops_url': OPS_URL}
            }
            ok, queue_number, msg = jbuild.build(params)
            if ok:
                job.queue_number = queue_number
                job.save()
                async_task('qtasks.tasks_build.build_number_binding', *[], **{'job_id': job.id, 'queue_number': queue_number,
                                                                              'appinfo_id': appinfo_obj.id, 'job_type': 'app'})
                try:
                    # 将当前构建记录存入缓存
                    cache.set(f"{CI_LATEST_KEY}{appinfo_obj.id}",
                              job, 60 * 60 * 24)
                except BaseException as e:
                    pass
                # 存入ElasticSearch
                try:
                    rds_transfer_es(BuildJobDocument, job)
                except BaseException as e:
                    logger.error(f'构建记录转存ES异常，原因：{e}')
                content = f"构建应用{appinfo_obj.app.name}，环境{appinfo_obj.environment.name}"
                if appinfo_obj.app.category == 'category.front':
                    content += f', 构建模块{modules}.'
                return True, data
            transaction.savepoint_rollback(init_point)
            return False, msg
        except Exception as err:
            transaction.savepoint_rollback(init_point)
            logger.exception(
                f'创建应用[{appinfo_obj.uniq_tag}]的Jenkins任务[{job_name}]失败, 原因: {err}')
            return False, f"创建构建任务失败, ERROR: {err}"
    except Exception as err:
        logger.exception(
            f'创建应用[{appinfo_obj.uniq_tag}]的Jenkins任务[{job_name}]异常, 原因: {err}')
        return False, f"创建构建任务失败, ERROR: {err}"


def check_user_deploy_perm(user_obj: UserProfile, app_obj: AppInfo, perms=None, pub_order: PublishOrder = None):
    """
    检测指定用户是否有发布权限
    :param user_obj: 用户信息
    :param app_obj:  某环境下应用信息
    :param perms: 用户权限列表
    :param pub_order: 发布工单信息, 如果不是工单应用，则不需要传递此参数
    :return: True 有权限 False 无权限
    """
    if perms is None:
        perms = []
    return True


@transaction.atomic
def app_deploy_handle(request_data, appinfo_obj: AppInfo, user=None):
    """

    :param request_data:   request.data
    :param appinfo_obj: AppInfo 应用数据
    :param image:   发布镜像地址
    :return:
    """
    init_point = transaction.savepoint()
    # 创建发布job
    logger.debug(f'开始创建工单发版Job####{request_data}@@@@')
    serializer = DeployJobSerializer(data=request_data)
    if not serializer.is_valid():
        err_msg = f'工单应用[{appinfo_obj.uniq_tag}]发版失败, 原因: {serializer.errors}！'
        logger.error(err_msg)
        return False, err_msg
    uniq_id = f'{request_data["appinfo_id"]}-{datetime.datetime.now().strftime("%Y%m%d%H%M%S")}'
    if request_data.get('modules', None):
        uniq_id += f'-{request_data["modules"]}'
    serializer.save(deployer=user, uniq_id=uniq_id)
    job = DeployJob.objects.get(id=serializer.data['id'])
    # 存入ElasticSearch
    try:
        rds_transfer_es(DeployJobDocument, job)
    except BaseException as e:
        logger.error(f'发布记录转存ES失败，原因：{e}')

    order_id = request_data.get('order_id', None)
    jobid = job.id
    image = job.image
    targets = job.kubernetes if appinfo_obj.app.is_k8s == 'k8s' else request_data.get(
        'hosts', [])
    partial_deploy_replicas = request_data.get('partial_deploy_replicas', 0)
    partial_deploy_acceptance = request_data.get(
        'partial_deploy_acceptance', None)

    if appinfo_obj.app.category.split('.')[-1] == 'server' and appinfo_obj.app.is_k8s == 'k8s':

        try:
            if appinfo_obj.online == 10:
                # 已下线应用重新标记为上线
                appinfo_obj.online = 1
                appinfo_obj.save()
            # 标记应用集群状态为已申请上线
            KubernetesDeploy.objects.filter(
                kubernetes_id__in=targets).update(online=9)
            # 创建发布记录后发布应用
            deploy_yaml = template_generate(
                appinfo_obj, image, partial_deploy_replicas=partial_deploy_replicas)
            if deploy_yaml.get('ecode', 500) > 399:
                err_msg = f'发布生成k8s yaml异常 {deploy_yaml}'
                logger.debug(err_msg)
                transaction.savepoint_rollback(init_point)
                return False, err_msg
            if deploy_yaml.get('apm_yaml'):
                apm_mode = True
            else:
                apm_mode = False
            taskid = async_task('qtasks.tasks_deploy.app_deployment_handle',
                                jobid, deploy_yaml, True,
                                apm=apm_mode, partial_deploy_replicas=partial_deploy_replicas, partial_deploy_acceptance=partial_deploy_acceptance)
        except BaseException as e:
            logger.exception(f'发版异常：{e}')
            transaction.savepoint_rollback(init_point)
            return False, f'发版异常：{e}'
    else:
        app_flag = 'web'
        static = DataDict.objects.get(key='REMOTE_HOSTS')
        hosts = [static.value]
        target_hosts = appinfo_obj.hosts
        playfile = 'web_deploy.yaml'
        playfile4rollback = 'jar_rollback.yaml'
        if appinfo_obj.app.category.split('.')[-1] == 'server':
            # 非Kubernetes部署的后端应用
            app_flag = 'jar'
            logger.info(f'ansible目标主机==={target_hosts}')

            playfile = 'jar_deploy.yaml'
            if appinfo_obj.app.is_k8s == 'docker':
                app_flag = 'docker'
                playfile = 'docker_deploy.yaml'
            logger.info(f'非k8s部署后端应用==={hosts}###{targets}')

        forward_host = hosts[0].split(':')
        inventory = [{'hostname': forward_host[0], 'ip': forward_host[0], 'username': 'root',
                      'port': forward_host[1] if len(forward_host) == 2 else 22}]

        playbook = os.path.join(PLAYBOOK_PATH, playfile)
        playbook4rollback = os.path.join(PLAYBOOK_PATH, playfile)
        deploy_path = get_datadict(f'deploy_path.{app_flag}', config=1, default_value={
                                   "default": "/data/web"})
        deploy_path = deploy_path.get(appinfo_obj.app.project.product.name, None) or deploy_path.get('default',
                                                                                                     '/data/web')
        dest = f"{deploy_path}/{appinfo_obj.environment.name.lower()}/{appinfo_obj.app.project.name.replace('.', '-').lower()}/{appinfo_obj.app.name}"
        payload = {
            'app_flag': app_flag,
            'partial_deploy_acceptance': partial_deploy_acceptance,
            'app_name': appinfo_obj.app.name,
            'appid': appinfo_obj.app.appid,
            'product': appinfo_obj.app.project.product.name,
            'project': appinfo_obj.app.project.name,
            'src_env': image.split('-')[0], 'dest_env': appinfo_obj.environment.name.lower(),
            'src_tag': image.split(':')[-1],
            'image': image,
            'path_parent': deploy_path,
            'name': jobid, 'target_hosts': target_hosts, 'dest': dest,
            'playbook4rollback': playbook4rollback,
            'playbook': playbook, 'inventory': inventory, 'hosts': [forward_host[0]]}
        taskid = async_task(
            'qtasks.tasks_deploy.nonk8s_deploy_handle', **payload)
    return True, serializer.data


def deploy_handle(jobid, targets, appinfo_obj: AppInfo, image, force=None, partial_deploy_replicas: int = 0, partial_deploy_acceptance=None):
    """
    :return:
    """
    if appinfo_obj.app.category.split('.')[-1] == 'server' and appinfo_obj.app.is_k8s == 'k8s':
        # 标记应用集群状态为已申请上线
        KubernetesDeploy.objects.filter(
            kubernetes_id__in=targets).update(online=9)
        # 创建发布记录后发布应用
        deploy_yaml = template_generate(
            appinfo_obj, image, partial_deploy_replicas=partial_deploy_replicas)
        logger.debug(f'发布生成k8s yaml文件 {deploy_yaml}')
        if deploy_yaml.get('apm_yaml'):
            apm_mode = True
        else:
            apm_mode = False
        taskid = async_task('qtasks.tasks_deploy.app_deployment_handle',
                            jobid, deploy_yaml, force,
                            apm=apm_mode, partial_deploy_replicas=partial_deploy_replicas, partial_deploy_acceptance=partial_deploy_acceptance)
    else:
        app_flag = 'web'
        static = DataDict.objects.get(key='REMOTE_HOSTS')
        hosts = [static.value]
        # 默认取应用关联的主机信息
        target_hosts = appinfo_obj.hosts
        playfile = 'web_deploy.yaml'
        playfile4rollback = 'jar_rollback.yaml'
        if appinfo_obj.app.category.split('.')[-1] == 'server':
            # 非Kubernetes部署的后端应用
            app_flag = 'jar'
            playfile = 'jar_deploy.yaml'
            if appinfo_obj.app.is_k8s == 'docker':
                app_flag = 'docker'
                playfile = 'docker_deploy.yaml'
            logger.info(f'非k8s部署后端应用==={hosts}###{targets}')

        forward_host = hosts[0].split(':')
        inventory = [{'hostname': forward_host[0], 'ip': forward_host[0], 'username': 'root',
                      'port': forward_host[1] if len(forward_host) == 2 else 22}]
        playbook = os.path.join(PLAYBOOK_PATH, playfile)
        playbook4rollback = os.path.join(PLAYBOOK_PATH, playfile)
        deploy_path = get_datadict(f'deploy_path.{app_flag}', config=1, default_value={
                                   "default": "/data/web"})
        deploy_path = deploy_path.get(appinfo_obj.app.project.product.name, None) or deploy_path.get('default',
                                                                                                     '/data/web')
        dest = f"{deploy_path}/{appinfo_obj.environment.name.lower()}/{appinfo_obj.app.project.name.replace('.', '-').lower()}/{appinfo_obj.app.name}"
        payload = {
            'app_flag': app_flag,
            'partial_deploy_acceptance': partial_deploy_acceptance,
            'app_name': appinfo_obj.app.name,
            'appid': appinfo_obj.app.appid,
            'product': appinfo_obj.app.project.product.name,
            'project': appinfo_obj.app.project.name,
            'src_env': image.split('-')[0], 'dest_env': appinfo_obj.environment.name.lower(),
            'src_tag': image.split(':')[-1],
            'image': image,
            'path_parent': deploy_path,
            'name': jobid, 'target_hosts': target_hosts, 'dest': dest,
            'playbook4rollback': playbook4rollback,
            'playbook': playbook, 'inventory': inventory, 'hosts': [forward_host[0]]}
        taskid = async_task(
            'qtasks.tasks_deploy.nonk8s_deploy_handle', **payload)
    return {'code': 200}
