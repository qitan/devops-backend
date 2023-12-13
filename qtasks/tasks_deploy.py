import base64
import json
import socket
import time
import datetime
import logging
import pytz
from django_q.tasks import async_task, schedule
from django_q.models import Schedule
from django.db import transaction
from django.core.cache import cache
from dbapp.models import KubernetesCluster, AppInfo, KubernetesDeploy, Environment
from dbapp.models import Project
from common.MailSend import OmsMail
from common.ext_fun import get_datadict, k8s_cli, template_generate, template_svc_generate, get_datadict, time_convert
from common.kubernetes_utils import deployment_check
from common.utils.AnsibleCallback import AnsibleApi, PlayBookResultsCollector
from common.utils.HarborAPI import HarborAPI
from common.utils.RedisAPI import RedisManage
from common.variables import HARBOR_SECRET, MSG_KEY, CD_LATEST_KEY, DEPLOY_NUM_MAP, APP_COLOR_MAP, APP_STATUS_MAP, \
    G_CD_TYPE, \
    DELAY_NOTIFY_KEY, CD_WEB_RESULT_KEY, ANSIBLE_STATUS, DEPLOY_MAP, CD_RESULT_KEY
from config import WORKFLOW_TEMPLATE_IDS
from deploy.documents import DeployJobDocument
from dbapp.model.model_deploy import DeployJob, CD_STAGE_RESULT_KEY, PublishApp, PublishOrder, DeployJobResult
from deploy.rds_transfer import rds_transfer_es
from deploy.serializers import DeployJobSerializer
from qtasks.tasks import clean_image_task

from dbapp.model.model_ucenter import SystemConfig, DataDict, UserProfile
from workflow.ext_func import create_workflow
from dbapp.model.model_workflow import Workflow, WorkflowNodeHistory, WorkflowTemplate
from workflow.notice import NoticeProxy

logger = logging.getLogger(__name__)


TASK_FOR_MR_KEY = 'qtasks:mr:'


def get_job(job_id):
    try:
        job = DeployJob.objects.get(id=job_id)
        return True, job
    except DeployJob.DoesNotExist:
        logger.debug(f'获取发布任务[ID: {job_id}]失败.')
        return False, f'获取发布任务[ID: {job_id}]失败.'


class K8sDeploys(object):
    CACHE_EXPIRE_SECOND = 60 * 30

    def __init__(
            self,
            job_obj: DeployJob,
            appinfo_obj,
            k8s_clusters,
            deploy_yaml_src,
            apm_mode: False,
            force=False,
            partial_deploy_replicas=0,
            partial_deploy_acceptance=None,
    ):
        """

        :param job_obj: DeployJob
        :param appinfo_obj: AppInfo
        :param k8s_clusters: KubernetesCluster
        :param deploy_yaml_src:
        :param apm_mode:
        :param force:
        :param partial_deploy_replicas:
        :param partial_deploy_acceptance:
        """
        self.job_obj = job_obj
        self.appinfo_obj = appinfo_obj
        self.k8s_clusters = k8s_clusters
        self.deploy_yaml_src = deploy_yaml_src
        self.partial_deploy_replicas = partial_deploy_replicas
        self.partial_deploy_acceptance = partial_deploy_acceptance
        self.force = force
        self.apm_mode = apm_mode
        self.namespace = self.appinfo_obj.namespace
        self.version_prev = self.appinfo_obj.version
        self.full_image = deploy_yaml_src['image']
        self.image_with_tag = '/'.join(self.full_image.split('/')[1:])
        _image = self.full_image.split('/')[-1].split(':')
        self.image_repo = f"{self.namespace}/{_image[0]}"
        self.image_tag = _image[1]

        # 通知消息key
        self.msg_key = f"{MSG_KEY}{self.appinfo_obj.environment.name}:{self.appinfo_obj.app.appid}:{self.image_tag.split('_')[0]}"
        # 通知消息延时
        self.notice_delay = 0.1

        self.cd_result = {}
        self.init_result()
        self.stage_list = []
        self.cur_k8s_deploy = None
        self.cur_k8s_deploy_cache_key_prefix = None

    def init_result(self):
        self.cd_result = {
            'status': 3,
            'col_active': '',
            'worker': socket.gethostname()
        }
        for i in self.k8s_clusters:
            self.cd_result[i.name] = {
                'stages': [],
                'status': 0
            }

    def init_deploy_job_status(self):
        # 更改当前发布状态为发布中
        self.job_obj.status = 3
        self.job_obj.save()

        # 发布工单，获取当前发布应用
        if self.job_obj.order_id:
            # 工单通知消息key
            self.msg_key = f"{MSG_KEY}{self.job_obj.order_id}"
            # 更改当前应用状态为发布中
            pub_app = PublishApp.objects.filter(
                appinfo_id=self.job_obj.appinfo_id, order_id=self.job_obj.order_id)
            pub_app.update(status=3)
            # 更改当前工单状态为发布中
            pub_order = PublishOrder.objects.get(
                order_id=self.job_obj.order_id)
            pub_order.status = 3
            pub_order.save()
            # 工单采用不同的通知延时， 更新 延时时间
            order_delay = get_datadict('ORDER_NOTIFY_DELAY', config=1)
            if order_delay:
                self.notice_delay = order_delay['delay']
            else:
                self.notice_delay = 60

    def update_deploy_job_status(self):
        # 更新部署结果缓存
        cache.set(f'appdeploy:{self.job_obj.id}',
                  self.cd_result, self.CACHE_EXPIRE_SECOND)

        # 保存最终的集群部署状态
        self.job_obj.status = self.cd_result['status']
        self.job_obj.result = self.cd_result
        self.job_obj.save()

        # 同步设置发布工单的状态
        if self.job_obj.order_id:
            # 发布工单，获取当前工单所有发布应用
            pub_app = PublishApp.objects.filter(
                appinfo_id=self.job_obj.appinfo_id, order_id=self.job_obj.order_id)
            pub_order = PublishOrder.objects.get(
                order_id=self.job_obj.order_id)
            # 更改当前应用状态
            pub_app.update(status=self.cd_result['status'])
            # 这里判断要排除 status = 4  即已经作废的应用
            app_status = [i.status for i in PublishApp.objects.filter(
                order_id=self.job_obj.order_id).exclude(status=4)]
            if len(set(app_status)) == 1 and app_status[0] == 1:
                # 所有应用发布成功
                pub_order.status = 1
                # 通知延时
                self.notice_delay = 0.1
            elif 0 in app_status or 3 in app_status:
                # 存在未发版或者发版中的应用, 标记工单状态为发版中
                pub_order.status = 3
            else:
                # 其它状态判定为失败
                pub_order.status = 2
                # 通知延时
                self.notice_delay = 0.1
            pub_order.save()

    def notify_deploy_result(self):
        """
        部署结果通知
        :return:
        """
        cd_status = self.cd_result['status']
        notify = self.appinfo_obj.app.project.notify
        if self.job_obj.order_id:
            # 从项目发布定义获取发版通知机器人
            release_config = self.appinfo_obj.app.project.projectenvreleaseconfig_set.filter(
                environment=self.appinfo_obj.environment)
            if release_config.first():
                notify = release_config.first().config.get('notify', None)
                if notify:
                    notify = {'robot': notify[1]}
            else:
                # 工单发版应用通知到生产群, 增加数据字典 PUBLISHORDER_NOTIFY
                try:
                    notify_key = 'PUBLISH_NOTIFY'
                    notify = {'robot': None}
                    if get_datadict(notify_key):
                        notify = {'robot': get_datadict(notify_key)['value']}
                    if get_datadict(f'{notify_key.lower()}.{self.appinfo_obj.app.project.product.name}'):
                        notify = {'robot': get_datadict(f'{notify_key.lower()}.{self.appinfo_obj.app.project.product.name}')[
                            'value']}
                except BaseException as e:
                    logger.exception(
                        f'应用[{self.appinfo_obj.uniq_tag}]发布消息通知失败, 原因: 获取通知机器人失败, {e}')

        if notify.get('mail', None) or notify.get('robot', None):
            title = f"{self.appinfo_obj.app.appid}发布{DEPLOY_NUM_MAP[cd_status][0]}"
            k8s_result = ''
            for i in self.k8s_clusters:
                k8s_result += f"  - <font color={APP_COLOR_MAP[self.cd_result[i.name]['status']]}>{i.name}: {APP_STATUS_MAP[self.cd_result[i.name]['status']]}  </font>  "
            deploy_type_msg = dict(G_CD_TYPE)[self.job_obj.deploy_type]
            if self.job_obj.deploy_type == 2:
                # 回退类型加粗显示
                deploy_type_msg = f'  **<font color="#f56c6c">{deploy_type_msg}</font>**'
            msg = f'''**<font color="{DEPLOY_NUM_MAP[cd_status][1]}">{DataDict.objects.get(key=self.appinfo_obj.app.category).value} 发布 {DEPLOY_NUM_MAP[cd_status][0]}</font>**  
项目: {self.appinfo_obj.app.project.alias}  
环境: {self.appinfo_obj.environment.name}  
应用ID: {self.appinfo_obj.app.appid}  
类型: {deploy_type_msg}  
版本: {self.version_prev} 更新至 {self.image_tag}  
目标集群:  
{k8s_result}  
发布者: {self.job_obj.deployer.first_name or self.job_obj.deployer.username}  
发布时间: {time_convert(self.job_obj.created_time)}  
            '''
            logger.info(f'发布结果消息通知格式内容： {msg}')
            # 云之家通知
            if notify.get('robot', None):
                robot = notify['robot']
                recv_phone = self.job_obj.deployer.mobile
                recv_openid = self.job_obj.deployer.feishu_openid
                cache.set(
                    f"{self.msg_key}:cd:{self.job_obj.id}",
                    {
                        'appid': self.appinfo_obj.app.appid, 'order_id': self.job_obj.order_id,
                        'robot': robot, 'recv_phone': recv_phone, 'recv_openid': recv_openid,
                        'msg_key': self.msg_key, 'msg': msg, 'title': title
                    },
                    60 * 60 * 3
                )
                cache.set(
                    f"{DELAY_NOTIFY_KEY}{self.msg_key}",
                    {
                        'curr_time': datetime.datetime.now(),
                        'delay': self.notice_delay
                    },
                    60 * 60 * 3
                )
                taskid = schedule('qtasks.tasks.deploy_notify_queue', *[self.msg_key],
                                  **{
                    'appid': self.appinfo_obj.app.appid, 'order_id': self.job_obj.order_id, 'robot': robot,
                    'recv_phone': recv_phone, 'recv_openid': recv_openid, 'msg_key': self.msg_key, 'title': title
                },
                    schedule_type=Schedule.ONCE,
                    next_run=datetime.datetime.now() + datetime.timedelta(seconds=self.notice_delay)
                )

    def run(self):
        # 初始化应用和工单数据 & 状态
        self.init_deploy_job_status()

        all_status = []

        # 遍历应用绑定的K8S集群， 挨个集群都执行部署
        for index, k8s in enumerate(self.k8s_clusters):
            k8s_deploy_obj = KubernetesDeploy.objects.filter(
                appinfo=self.appinfo_obj, kubernetes=k8s)
            self.cur_k8s_deploy = K8sDeploy(
                k8s,
                self.job_obj,
                self.appinfo_obj,
                self.namespace,
                self.deploy_yaml_src,
                self.cd_result,
                self.full_image,
                self.image_with_tag,
                self.image_repo,
                self.image_tag,
                force=self.force,
            )
            is_update_image_tag = True
            try:
                # 连接K8S集群
                self.cur_k8s_deploy.stage_get_k8s_client()
                self.cur_k8s_deploy.deploy_flow_standard()
            except Exception as e:
                logger.exception(
                    f'集群 {k8s} 任务步骤 {self.cur_k8s_deploy.cur_stage} 出现问题，直接跳到执行下一个集群, 异常原因： {e.__class__} {e}')

            # 生成单个集群的部署状态
            self.cur_k8s_deploy.generate_deploy_status()

            # 发布成功， 更新应用在当前集群最新的镜像标签
            if is_update_image_tag is True and self.cd_result[k8s.name]['status'] == 1:
                k8s_deploy_obj.update(version=self.image_tag)

            all_status.append(self.cd_result[k8s.name]['status'])
        if len(set(all_status)) == 1 and all_status[0] == 1:
            # 所有集群状态值为1, 则判定应用部署成功
            self.cd_result['status'] = 1
            # 所有集群部署成功， 更新当前镜像tag
            self.appinfo_obj.version = self.image_tag
            self.appinfo_obj.save()
        else:
            self.cd_result['status'] = 2
            self.notice_delay = 5

        self.update_deploy_job_status()
        DeployJobResult.objects.create(
            **{'job_id': self.job_obj.id, 'result': json.dumps(self.cd_result)})
        try:
            cache.set(f"{CD_LATEST_KEY}{self.appinfo_obj.id}",
                      self.job_obj, 60 * 60 * 24 * 3)
            cache.set(f"{CD_RESULT_KEY}{self.job_obj.id}", {
                      'result': self.cd_result}, 60 * 60 * 24 * 3)
        except BaseException as e:
            logger.exception(
                f"缓存应用[{self.appinfo_obj.uniq_tag}]最新发布记录异常, 将把缓存key删除。异常原因: {e}.")
            cache.delete(f"{CD_LATEST_KEY}{self.appinfo_obj.id}")

        # 发送结束标志
        cache.set(f'appdeploy:stat:{self.job_obj.id}', 1)
        time.sleep(5)

        self.notify_deploy_result()


class K8sDeploy(object):
    # 默认的 cache key 超时时间
    CACHE_EXPIRE_SECOND = K8sDeploys.CACHE_EXPIRE_SECOND

    def __init__(
            self,
            k8s_obj: KubernetesCluster,
            deploy_job_obj: DeployJob,
            appinfo_obj: AppInfo,
            namespace,
            deploy_yaml_src,
            cd_result,
            full_image,
            image_with_tag,
            image_repo,
            image_tag,
            force=False,
    ):
        """
        :param k8s_obj:
        :param deploy_job_obj:
        :param appinfo_obj:
        :param namespace: deploy namespace
        """
        self.k8s_obj = k8s_obj
        self.k8s_cli = None
        self.deploy_job_obj = deploy_job_obj
        self.appinfo_obj = appinfo_obj
        self.namespace = namespace
        self.deploy_yaml_src = deploy_yaml_src
        self.deploy_yaml = deploy_yaml_src['yaml']
        self.deployment_name = self.deploy_yaml['metadata']['name']
        self.api_version = self.k8s_obj.version.get('apiversion', 'apps/v1')

        self.full_image = full_image
        self.image_with_tag = image_with_tag
        self.image_repo = image_repo
        self.image_tag = image_tag
        self.force = force
        self.cd_result = cd_result
        self.stage_list = []
        self.cur_stage = None
        self.msg_key = f"{MSG_KEY}{self.deploy_job_obj.order_id}"
        self.cache_key_prefix = f"{CD_STAGE_RESULT_KEY}{self.msg_key}:{self.deploy_job_obj.id}::{self.k8s_obj.name}"
        # 更新当前集群标记
        self.cd_result['col_active'] = self.k8s_obj.name

    def get_k8s_client(self):
        try:
            k8s_config = json.loads(self.k8s_obj.config)
        except BaseException as e:
            msg = f'应用[{self.appinfo_obj.uniq_tag}]连接K8S集群失败, 原因: Kubernetes[{self.k8s_obj.name}]配置异常, {e}'
            logger.error(msg)
            _stat = 2
            ret = {'message': {'err': str(e)}}
            return _stat, msg, ret

        cli = k8s_cli(self.k8s_obj, k8s_config)
        if not cli[0]:
            msg = f'应用[{self.appinfo_obj.uniq_tag}]连接K8S集群, 原因: Kubernetes配置异常, {cli[1]}'
            logger.error(msg)
            _stat = 2
            ret = {'message': {'err': cli[1]}}
            return _stat, msg, ret

        self.k8s_cli = cli[1]
        return 1, '', ''

    def deploy_flow_standard(self):
        """
        标准发布流程
        :return:
        """
        self.stage_image_sync()
        self.stage_app_deploy()
        self.stage_app_deploy_status()

    def stage_get_k8s_client(self, stage_name='连接K8S集群'):
        stat, msg, ret = self.get_k8s_client()
        if stat == 2:
            self.init_stage(stage_name)
            self.save_stage_result(stat, msg, ret)
        if stat != 1:
            raise AssertionError('连接K8S集群失败')

    def stage_image_sync(self, stage_name='镜像同步'):
        if self.deploy_job_obj.order_id:
            self.init_stage(stage_name)
            image = self.image_with_tag
            if self.appinfo_obj.environment.name == 'pro':
                image = image.replace('pro-', 'uat-')
            stat, msg, ret = self.image_sync(
                self.image_repo, image, self.image_tag)
            self.save_stage_result(stat, msg, ret)
            logger.info(f'image_sync stat, msg, ret === {stat}, {msg}, {ret}')
            self.validate_stat(stat)

    def stage_app_deploy(self, stage_name='应用部署', deployment_name=None, deploy_yaml=None):
        self.init_stage(stage_name)
        if not deployment_name:
            deployment_name = self.deploy_yaml['metadata']['name']
        if not deploy_yaml:
            deploy_yaml = self.deploy_yaml
        # 默认替换掉版本号
        deploy_yaml['apiVersion'] = self.api_version
        stat, msg, ret = self.app_deploy(deployment_name, deploy_yaml)
        self.save_stage_result(stat, msg, ret)
        self.validate_stat(stat)

    def stage_app_deploy_status(self, stage_name='状态检测', deployment_name=None, verify_image_tag=True):
        """
        获取 app pod 状态
        :param stage_name: 步骤名
        :param deployment_name: deploy 名称
        :param verify_image_tag: 是否验证镜像tag版本
        :return:
        """
        self.init_stage(stage_name)
        if not deployment_name:
            deployment_name = self.deploy_yaml['metadata']['name']
        stat, msg, ret = self.check_app_deploy(
            deployment_name, tag=verify_image_tag and self.image_tag or None)
        self.save_stage_result(stat, msg, ret)
        self.validate_stat(stat)

    def init_status(self):
        self.cd_result[self.k8s_obj.name]['status'] = 3
        cache.set(f'appdeploy:{self.deploy_job_obj.id}',
                  self.cd_result, self.CACHE_EXPIRE_SECOND)
        self.deploy_job_obj.result = self.cd_result
        self.deploy_job_obj.save()

    def validate_stat(self, stat: int):
        if stat != 1:
            raise AssertionError('步骤执行失败了， 状态不等于1')

    def init_stage(self, stage_name):
        self.stage_list.append(stage_name)
        self.cur_stage = stage_name
        self.cd_result[self.k8s_obj.name]['stages'].append({
            'name': stage_name,
            'status': 0,  # 状态0 初始， 1 成功 2失败
            'msg': '',
            'logs': ''
        })
        cache.set(f'appdeploy:{self.deploy_job_obj.id}',
                  self.cd_result, self.CACHE_EXPIRE_SECOND)
        self.deploy_job_obj.result = self.cd_result
        self.deploy_job_obj.save()

    def save_stage_result(self, stat, msg, ret):
        if isinstance(ret, str):
            ret = json.loads(ret)
        deploy_stage_index = self.stage_list.index(self.cur_stage)
        deploy_content = {
            'name': self.cur_stage,
            'status': stat,
            'msg': msg,
            'logs': json.dumps('message' in ret and ret['message'] or ret)
        }
        self.cd_result[self.k8s_obj.name]['stages'][deploy_stage_index] = deploy_content
        stage_cache_key = f"{self.cache_key_prefix}::::{deploy_stage_index}"
        cache.set(stage_cache_key, deploy_content, self.CACHE_EXPIRE_SECOND)
        cache.set(f'appdeploy:{self.deploy_job_obj.id}',
                  self.cd_result, self.CACHE_EXPIRE_SECOND)
        self.deploy_job_obj.result = self.cd_result
        self.deploy_job_obj.save()

    def image_sync(self, repo, image, tag):
        """
        镜像同步
        :return:
        """
        try:
            harbor = SystemConfig.objects.get(id=self.k8s_obj.idc.repo)
            # 获取harbor配置
            harbor_config = json.loads(harbor.config)
            # 调用Harbor api同步镜像
            cli = HarborAPI(
                url=harbor_config['ip'] + '/api/',
                username=harbor_config['user'],
                password=harbor_config['password']
            )
            # 检测镜像标签是否存在
            res = cli.fetch_tag(repo, tag)
            if res.get('ecode', 500) <= 399:
                return 1, "镜像已存在，跳过同步步骤", json.dumps(res)

            # 镜像标签不存在, 执行打标签逻辑
            res = cli.patch_tag(repo, image, tag)
            if res.get('ecode', 500) > 399:
                return 2, "镜像标签不存在, 执行打标签逻辑失败", json.dumps(res)
            if isinstance(res['data'], bytes):
                res['data'] = res['data'].decode('utf-8')
            return 1, '镜像同步成功', json.dumps(res)
        except BaseException as e:
            logger.exception(f"镜像同步[{self.k8s_obj.idc.repo}]异常, 原因: {e}")
            return 2, '镜像同步异常', {'message': e}

    def app_deploy(self, deployment_name, deploy_yaml):
        msg = ''
        if isinstance(deploy_yaml, dict):
            deploy_yaml = json.dumps(deploy_yaml)

        self.check_namespace()
        self.check_svc()
        try:
            ret = self.k8s_cli.fetch_deployment(
                deployment_name, self.namespace, self.api_version)
            if ret.get('ecode', 200) > 399:
                msg += f"Deployment[{deployment_name}]不存在，即将部署！\n"
                ret = self.k8s_cli.create_namespace_deployment(
                    deployment_name,
                    deploy_yaml=deploy_yaml,
                    namespace=self.namespace
                )
                if ret.get('ecode', 200) > 399:
                    # 部署异常
                    msg = f"部署应用{self.appinfo_obj.app.alias}[{deployment_name}]到Kubernetes集群[{self.k8s_obj.name}]失败\n"
                    stat = 2
                    return stat, msg, ret

                # 部署无异常
                msg += f"部署应用{self.appinfo_obj.app.alias}[{deployment_name}]到Kubernetes集群[{self.k8s_obj.name}]完成\n"
                stat = 1
                return stat, msg, ret

            msg += f"准备更新Deployment[{deployment_name}]\n"
            ret = self.k8s_cli.update_deployment(
                deployment_name,
                deploy_yaml=deploy_yaml,
                namespace=self.namespace,
                api_version=self.api_version,
                force=self.force
            )
            if ret.get('ecode', 200) > 399:
                # 部署异常
                msg += f"部署应用{self.appinfo_obj.app.alias}[{deployment_name}]到Kubernetes集群[{self.k8s_obj.name}]失败\n"
                stat = 2
                return stat, msg, ret

            # 部署无异常
            msg += f"部署应用{self.appinfo_obj.app.alias}[{deployment_name}]到Kubernetes集群[{self.k8s_obj.name}]完成\n"
            stat = 1
            return stat, msg, ret
        except BaseException as e:
            err_msg = f'应用[{self.appinfo_obj.uniq_tag}]发布到Kubernetes集群[{self.k8s_obj.name}]失败, 原因: {e}'
            logger.exception(err_msg)
            stat = 2
            msg += f"{err_msg}\n"
            return stat, msg, {'message': str(e)}

    def check_app_deploy(self, deployment_name, tag=None):
        check_ret = deployment_check(
            self.k8s_cli, self.appinfo_obj, self.k8s_obj, tag, app_deploy_name=deployment_name)
        return check_ret['status'], check_ret['message'], check_ret['data']

    def check_namespace(self):
        try:
            # 创建命名空间
            r = self.k8s_cli.create_namespace(self.namespace)
        except BaseException as e:
            pass

        try:
            # 创建harbor secret
            harbor = SystemConfig.objects.get(id=self.k8s_obj.idc.repo)
            # 获取harbor配置
            harbor_config = json.loads(harbor.config)
            login_auth = base64.b64encode(json.dumps({'auths': {
                harbor_config['url']: {'username': harbor_config['user'],
                                       'password': harbor_config['password']}}}).encode('utf-8')).decode('utf-8')
            payload = {'data': {'.dockerconfigjson': login_auth}, 'kind': 'Secret',
                       'metadata': {'name': HARBOR_SECRET, 'namespace': self.namespace},
                       'type': 'kubernetes.io/dockerconfigjson'}
            r = self.k8s_cli.manage_secret(
                HARBOR_SECRET, self.namespace, **{'payload': payload})
        except BaseException as e:
            logger.exception(
                f'检测应用 [{self.appinfo_obj.uniq_tag}] harbor登录密钥 异常', e)
            pass

    def check_svc(self):
        # 获取svc模板
        try:
            ok, svc_yaml = template_svc_generate(self.appinfo_obj)
            if ok:
                # 获取svc
                r = self.k8s_cli.fetch_service(
                    self.appinfo_obj.app.name, self.namespace)
                if r.get('ecode', 200) == 404:
                    # 创建svc
                    r = self.k8s_cli.create_namespace_service(
                        self.appinfo_obj.app.name,
                        namespace=self.namespace,
                        svc_yaml=svc_yaml
                    )
                else:
                    # 更新svc
                    r = self.k8s_cli.update_namespace_service(
                        self.appinfo_obj.app.name,
                        namespace=self.namespace,
                        svc_yaml=svc_yaml
                    )
        except BaseException as e:
            pass

    def generate_deploy_status(self):
        """
        生成单个集群的部署状态
        :return:
        """
        k8s_status = [i['status']
                      for i in self.cd_result[self.k8s_obj.name]['stages']]
        if len(set(k8s_status)) == 1 and k8s_status[0] == 1:
            # 所有状态值为1,则判定该集群应用部署成功
            self.cd_result[self.k8s_obj.name]['status'] = 1
        elif 4 in k8s_status:
            # 状态值为4, 检测超时
            self.cd_result[self.k8s_obj.name]['status'] = 4
        else:
            # 其它情况判定失败
            self.cd_result[self.k8s_obj.name]['status'] = 2

        try:
            self.deploy_job_obj.result = self.cd_result
            self.deploy_job_obj.save()
            cache.set(f'appdeploy:{self.deploy_job_obj.id}',
                      self.cd_result, self.CACHE_EXPIRE_SECOND)
        except Exception as e:
            logger.exception(f'保存单个集群的部署情况失败, 原因 {e}')


def app_deployment_handle(
        job_id,
        deploy_yaml_src,
        force,
        apm=False,
        partial_deploy_replicas=0,
        partial_deploy_acceptance=None,
):

    _get_job_flag = True
    count = 0
    while _get_job_flag:
        count += 1
        ok, job = get_job(job_id)
        if ok or count > 30:
            _get_job_flag = False
        time.sleep(0.5)
    appinfo_objs = AppInfo.objects.filter(id=job.appinfo_id)
    if len(appinfo_objs) == 0:
        logger.error(f'获取不到应用[ID: {job.appinfo_id}], 部署失败!')
        job.status = 2
        job.save()
        return

    # 标识应用正在部署中
    appinfo_obj = appinfo_objs.first()
    version_prev = appinfo_obj.version
    appinfo_objs.update(online=3)

    # 从应用关联的k8s集群中过滤需要部署的k8s
    k8s_clusters = appinfo_obj.kubernetes.filter(id__in=job.kubernetes)
    if k8s_clusters.count() <= 0:
        logger.error(
            f'应用[{appinfo_obj.uniq_tag}]发版失败, 原因: 该应用未配置Kubernetes集群!')
        job.status = 2
        job.save()
        return

    deploys = K8sDeploys(
        job, appinfo_obj, k8s_clusters, deploy_yaml_src,
        apm, force=force,
        partial_deploy_replicas=partial_deploy_replicas,
        partial_deploy_acceptance=partial_deploy_acceptance
    )
    deploys.run()


class JarDeploy(object):
    def __init__(
            self, app_name, appid, product_name, project_name,
            is_micro, src_env, src_tag, image, dest_env, path_parent, dest, job_id,
            target_hosts: list, playbook, inventory: list, hosts: list, partial_deploy_acceptance=None,
            playbook4rollback=None
    ):
        self.partial_deploy_acceptance = partial_deploy_acceptance
        self.app_name = app_name
        self.appid = appid
        self.product_name = product_name
        self.project_name = project_name
        self.is_micro = is_micro
        self.src_env = src_env
        self.src_tag = src_tag
        self.job_id = job_id
        self.target_hosts = target_hosts
        self.path_parent = path_parent
        self.dest_env = dest_env
        self.dest = dest
        self.playbook = playbook
        self.playbook4rollback = playbook4rollback
        self.inventory = inventory
        self.hosts = hosts

        _get_job_flag = True
        count = 0
        while _get_job_flag:
            count += 1
            ok, self.job_obj = get_job(job_id)
            if ok or count > 30:
                _get_job_flag = False
            time.sleep(0.5)
        try:
            self.job_result_obj = DeployJobResult.objects.get(
                job_id=self.job_id)
        except:
            DeployJobResult.objects.create(job_id=self.job_id)
            self.job_result_obj = DeployJobResult.objects.get(
                job_id=self.job_id)
        self.appinfo_obj = AppInfo.objects.get(id=self.job_obj.appinfo_id)
        self.version_prev = self.appinfo_obj.version
        if self.appinfo_obj.app.category == 'category.front':
            # 前端
            try:
                front_deploy_jobs = DeployJob.objects.filter(appinfo_id=self.appinfo_obj.id, status=1,
                                                             modules=self.job_obj.modules)
                if front_deploy_jobs:
                    self.version_prev = front_deploy_jobs.first(
                    ).image.split(':')[-1]
            except BaseException as e:
                logger.warning(
                    f'获取应用[{self.appinfo_obj.app.name}]上个版本异常，原因：{e}')
        self.redis_conn = RedisManage().conn()
        self.cd_result = {'DEVOPS': {'stages': [], 'status': 0}, 'status': 0, 'col_active': 'DEVOPS',
                          'worker': socket.gethostname()}
        self.step_status = []
        self.deploy_job_cache_key = f'{CD_WEB_RESULT_KEY}{job_id}'
        # 通知消息key
        self.msg_key = f"{MSG_KEY}{self.appinfo_obj.environment.name}:{self.appinfo_obj.app.appid}:{src_tag.split('_')[0]}"
        # 通知延时
        self.notice_delay = 0.1
        self.pub_app = None
        self.pub_order = None
        # 存储目标主机发布key
        self.jar_batch_key = f'batchdeploy::{self.appinfo_obj.id}::{self.job_id}'
        # 发布主机列表
        self.host_deployed = []
        # Harbor配置
        # TODO：非k8s部署后端指定harbor
        harbor = SystemConfig.objects.filter(type='cicd-harbor').first()
        # 获取harbor配置
        self.harbor_config = json.loads(harbor.config)
        self.image = f'{self.harbor_config["url"].split("//")[-1]}/{image}'
        self.init_result()

    def init_result(self):
        self.job_result_obj.result = json.dumps(self.cd_result)
        if self.job_obj.order_id:
            self.jar_batch_key = f'batchdeploy::{self.appinfo_obj.id}::{self.job_obj.order_id}'
            self.msg_key = f"{MSG_KEY}{self.job_obj.order_id}"
            # 更改当前应用状态为发布中
            self.pub_app = PublishApp.objects.filter(appinfo_id=self.job_obj.appinfo_id,
                                                     order_id=self.job_obj.order_id)
            if self.job_obj.modules:
                self.pub_app = self.pub_app.filter(
                    modules=self.job_obj.modules)
            self.pub_app = self.pub_app.first()
            self.pub_app.status = 3
            self.pub_app.save()
            # 更改当前工单状态为发布中
            self.pub_order = PublishOrder.objects.get(
                order_id=self.job_obj.order_id)
            self.pub_order.status = 3
            self.pub_order.save()
            order_delay = get_datadict('ORDER_NOTIFY_DELAY', config=1)
            if order_delay:
                self.notice_delay = order_delay['delay']
            else:
                self.notice_delay = 60
        # 更改当前发布状态为发布中
        self.job_obj.status = 3
        self.job_obj.save()
        self.job_result_obj.save()

    def generate_result(self):
        ret = self.redis_conn.lrange(self.job_obj.id, 0, -1)
        self.cd_result['DEVOPS']['stages'] = []
        for (index, i) in enumerate(ret):
            item = json.loads(i)
            for _, v in item.items():
                for _, v1 in v.items():
                    self.step_status.append(1 if v1['status'] in [
                                            'success', 'skipped', 'skip'] else 0)
                    list_flag = 0
                    target_logs = []
                    if v1['msg'].get('results', None):
                        if isinstance(v1['msg']['results'], (list,)):
                            list_flag = 1
                            for j in v1['msg']['results']:
                                j['stderr_lines'] = '<omitted>'
                                j.pop('invocation', None)
                                target_key = j.pop('_ansible_item_label', None)
                                if target_key:
                                    target_logs.append({
                                        'name': target_key,
                                        'status': 1 if j['rc'] == 0 else 2,
                                        'logs': json.dumps(j)
                                    })
                    self.cd_result['DEVOPS']['stages'].append({
                        'name': v1['task'],
                        'status': ANSIBLE_STATUS[v1['status']],
                        'logs': target_logs if list_flag else json.dumps(v1['msg'])
                    })

        cache.set(f'appdeploy:{self.job_obj.id}', self.cd_result)
        self.job_result_obj.result = json.dumps(self.cd_result)
        self.job_obj.save()

    def task_over(self, action_type):
        status = self.cd_result['status']
        self.job_result_obj.result = json.dumps(self.cd_result)
        self.job_result_obj.save()
        if action_type == 'rollback':
            # 回退应用标记
            self.job_obj.deploy_type = 2
        self.job_obj.status = status
        self.job_obj.save()

        if self.job_obj.order_id:
            self.pub_app.status = status
            if action_type == 'rollback':
                self.pub_app.deploy_type = 2
            self.pub_app.save()
            app_status = [i.status for i in PublishApp.objects.filter(
                order_id=self.job_obj.order_id)]
            if len(set(app_status)) == 1 and app_status[0] == 1:
                # 所有应用发布成功
                self.pub_order.status = 1
                # 通知延时
                self.notice_delay = 0.1
            elif 0 in app_status or 3 in app_status or 11 in app_status:
                # 存在未发版或者发版中的应用, 标记工单状态为发版中
                self.pub_order.status = 3
            else:
                # 其它状态判定为失败
                self.pub_order.status = 2
                # 通知延时
                self.notice_delay = 0.1
            self.pub_order.save()
        if action_type == 'rollback' or len(self.host_deployed) == len(self.appinfo_obj.hosts):
            # 回退操作或者所有主机已发布完成, 清理缓存
            cache.delete(self.jar_batch_key)
        self.notice()

    def notice(self):
        status = self.job_obj.status
        notify = self.appinfo_obj.app.project.notify
        if self.job_obj.order_id:
            # 从项目发布定义获取发版通知机器人
            release_config = self.appinfo_obj.app.project.projectenvreleaseconfig_set.filter(
                environment=self.appinfo_obj.environment)
            if release_config.first():
                notify = release_config.first().config.get(
                    'notify', None)
                if notify:
                    notify = {'robot': notify[1]}
            else:
                try:
                    notify_key = 'PUBLISH_NOTIFY'
                    notify = {'robot': None}
                    if get_datadict(notify_key):
                        notify = {'robot': get_datadict(notify_key)['value']}
                    if get_datadict(f'{notify_key.lower()}.{self.appinfo_obj.app.project.product.name}'):
                        notify = {'robot': get_datadict(f'{notify_key.lower()}.{self.appinfo_obj.app.project.product.name}')[
                            'value']}
                except BaseException as e:
                    logger.exception(
                        f'应用[{self.appinfo_obj.uniq_tag}]发布消息通知失败, 原因: 获取通知机器人失败, {e}')

        if notify.get('mail', None) or notify.get('robot', None):
            title = f"{self.appinfo_obj.app.appid}发布{DEPLOY_MAP[status == 1][0]}"
            deploy_type_msg = dict(G_CD_TYPE)[self.job_obj.deploy_type]
            if self.job_obj.deploy_type == 2:
                # 回退类型加粗显示
                deploy_type_msg = f'  **<font color="#f56c6c">{deploy_type_msg}</font>**'
            msg = f'''**<font color="{DEPLOY_NUM_MAP[status][1]}">{DataDict.objects.get(key=self.appinfo_obj.app.category).value} 发布 {DEPLOY_NUM_MAP[status][0]}</font>**    
项目: {self.appinfo_obj.app.project.alias}   
环境: {self.appinfo_obj.environment.name}  
应用ID: {self.appinfo_obj.app.appid}  
类型: {deploy_type_msg}  
版本: {self.version_prev} 更新至 {self.src_tag}  
目标主机:  
{self.host_deployed}   
发布者: {self.job_obj.deployer.name}    
发布时间: {time_convert(self.job_obj.created_time)}  
                '''
            # 云之家通知
            if notify.get('robot', None):
                robot = notify['robot']
                recv_phone = self.job_obj.deployer.mobile
                recv_openid = self.job_obj.deployer.feishu_openid
                cache.set(f"{self.msg_key}:cd:{self.job_obj.id}",
                          {'appid': self.appinfo_obj.app.appid, 'order_id': self.job_obj.order_id, 'robot': robot,
                           'recv_phone': recv_phone, 'recv_openid': recv_openid,
                           'msg_key': self.msg_key, 'msg': msg, 'title': title}, 60 * 60 * 3)
                cache.set(f"{DELAY_NOTIFY_KEY}{self.msg_key}",
                          {'curr_time': datetime.datetime.now(
                          ), 'delay': self.notice_delay},
                          60 * 60 * 3)
                taskid = schedule('qtasks.tasks.deploy_notify_queue', *[self.msg_key],
                                  **{'appid': self.appinfo_obj.app.appid, 'order_id': self.job_obj.order_id,
                                     'robot': robot,
                                     'recv_phone': recv_phone, 'recv_openid': recv_openid,
                                     'msg_key': self.msg_key, 'title': title},
                                  schedule_type=Schedule.ONCE,
                                  next_run=datetime.datetime.now() + datetime.timedelta(seconds=self.notice_delay)
                                  )

    def on_any_callback(self, callback_cls_obj: PlayBookResultsCollector, result, *args, **kwargs):
        self.generate_result()

    def run(self):
        action_type = 'update'
        try:
            self.host_deployed = self.target_hosts
            extra_data = {
                'app_name': self.app_name,
                'appid': self.appid,
                'is_micro': self.is_micro,
                'product': self.product_name,
                'project': self.project_name,
                'src_env': self.src_env,
                'src_tag': self.src_tag,
                'image': self.image,
                'target_hosts': self.host_deployed,
                'path_parent': self.path_parent,
                'dest_env': self.dest_env,
                'dest': self.dest,
                'hosts': self.hosts
            }
            if self.appinfo_obj.app.is_k8s == 'docker':
                # docker部署
                extra_data['service_command'] = ''
                if self.appinfo_obj.app.template.get('template', None):
                    if self.appinfo_obj.app.template['template'].get('command', None):
                        extra_data['service_command'] = self.appinfo_obj.app.template['template']['command']
                extra_data['harbor_url'] = self.harbor_config["url"].split(
                    "//")[-1]
                extra_data['harbor_user'] = self.harbor_config['user']
                extra_data['harbor_passwd'] = self.harbor_config['password']
            ansible_obj = AnsibleApi(
                redis_conn=self.redis_conn,
                chan=None,
                jid=self.job_id,
                channel=self.deploy_job_cache_key,
                inventory=self.inventory,
                extra_vars=extra_data,
                on_any_callback=self.on_any_callback
            )
            res = ansible_obj.playbookrun(
                playbook_path=[self.playbook if action_type ==
                               'update' else self.playbook4rollback]
            )
            if action_type == 'update':
                self.host_deployed.extend(self.target_hosts)
                self.host_deployed = list(set(self.host_deployed))
                cache.set(self.jar_batch_key, self.host_deployed)
        except Exception as e:
            logger.exception(f'调用 ansible api 执行 playbook 发生错误： {e}')
            self.cd_result['status'] = 2
            self.cd_result['DEVOPS']['stages'].append({
                'name': '执行异常',
                'status': 2,
                'logs': json.dumps({
                    e.__class__: str(e)
                })
            })
        else:
            if res.get('failed', None) or res.get('unreachable', None):
                logger.error(f'{self.app_name} 发布异常，中断发布')
                # 发布异常，标记为2, 任务结束
                self.cd_result['status'] = 2
                self.task_over(action_type)
                # 发布失败清缓存
                cache.delete(self.jar_batch_key)
                return
            if all(self.step_status):
                # 更新成功
                self.cd_result['status'] = 1
                if len(self.host_deployed) == len(self.appinfo_obj.hosts):
                    self.appinfo_obj.version = self.src_tag
                    self.appinfo_obj.save()
            else:
                self.cd_result['status'] = 2

            if action_type == 'update' and len(self.host_deployed) < len(self.appinfo_obj.hosts):
                # 存在未发布主机
                self.cd_result['status'] += 10
        self.task_over(action_type)
        cache.set(f'appdeploy:stat:{self.job_obj.id}', 1)


class WebDeploy(JarDeploy):
    def task_over(self, action_type):
        # 结果存入ES
        status = self.cd_result['status']
        self.job_result_obj.result = json.dumps(self.cd_result)
        self.job_result_obj.save()
        self.job_obj.status = status
        self.job_obj.save()

        if self.job_obj.order_id:
            self.pub_app.status = status
            self.pub_app.save()
            app_status = [i.status for i in PublishApp.objects.filter(
                order_id=self.job_obj.order_id)]
            if len(set(app_status)) == 1 and app_status[0] == 1:
                # 所有应用发布成功
                self.pub_order.status = 1
                # 通知延时
                self.notice_delay = 0.1
            elif 0 in app_status or 3 in app_status:
                # 存在未发版或者发版中的应用, 标记工单状态为发版中
                self.pub_order.status = 3
            else:
                # 其它状态判定为失败
                self.pub_order.status = 2
                # 通知延时
                self.notice_delay = 0.1
            self.pub_order.save()
        self.notice()

    def run(self):
        self.host_deployed = self.target_hosts
        extra_vars = {
            'app_name': self.app_name,
            'is_micro': self.is_micro,
            'product': self.product_name,
            'src_env': self.src_env,
            'src_tag': self.src_tag,
            'target_hosts': self.host_deployed,
            'dest_env': self.dest_env,
            'dest': self.dest,
            'hosts': self.hosts
        }
        try:
            ansible_obj = AnsibleApi(
                redis_conn=self.redis_conn,
                chan=None,
                jid=self.job_id,
                channel=self.deploy_job_cache_key,
                inventory=self.inventory,
                extra_vars=extra_vars,
                on_any_callback=self.on_any_callback
            )
            res = ansible_obj.playbookrun(
                playbook_path=[self.playbook]
            )
        except Exception as e:
            logger.exception(f'调用 ansible api 执行 playbook 发生错误： {e}')
            self.cd_result['status'] = 2
            self.cd_result['DEVOPS']['stages'].append({
                'name': '执行异常',
                'status': 2,
                'logs': json.dumps({
                    e.__class__: str(e)
                })
            })
        else:
            if res.get('failed', None) or res.get('unreachable', None):
                logger.error(f'{self.app_name} 发布异常，中断发布')
                # 发布异常，标记为2, 任务结束
                self.cd_result['status'] = 2
                self.task_over('update')
                return

            if all(self.step_status):
                # 更新成功
                self.cd_result['status'] = 1
                self.appinfo_obj.version = self.src_tag
                self.appinfo_obj.save()
            else:
                self.cd_result['status'] = 2
        self.task_over('update')
        cache.set(f'appdeploy:stat:{self.job_obj.id}', 1)


def nonk8s_deploy_handle(*args, **kwargs):
    cls_map = {'web': WebDeploy, 'jar': JarDeploy, 'docker': JarDeploy}
    playbook = kwargs.pop('playbook', None)
    playbook4rollback = kwargs.pop('playbook4rollback', None)
    inventory = kwargs.pop('inventory', None)
    name = kwargs.pop('name', None)

    app_name = kwargs['app_name']
    appid = kwargs['appid']
    product = kwargs['product']
    project = kwargs['project']
    src_env = kwargs['src_env']
    dest_env = kwargs['dest_env']
    src_tag = kwargs['src_tag']
    image = kwargs['image']
    target_hosts = kwargs['target_hosts']
    path_parent = kwargs['path_parent']
    dest = kwargs['dest']
    is_micro = kwargs.get('is_micro', None)
    hosts = kwargs['hosts']
    app_flag = kwargs['app_flag']
    partial_deploy_acceptance = kwargs['partial_deploy_acceptance']
    app_deploy = cls_map[app_flag](
        app_name,
        appid,
        product,
        project,
        is_micro,
        src_env,
        src_tag,
        image,
        dest_env,
        path_parent,
        dest,
        name,
        target_hosts,
        playbook,
        inventory,
        hosts,
        partial_deploy_acceptance,
        playbook4rollback
    )
    app_deploy.run()
