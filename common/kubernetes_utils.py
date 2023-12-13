#!/usr/bin/env python
# -*- encoding: utf-8 -*-
'''
@author  :   Charles Lai
@file    :   kubernetes_utils.py
@time    :   2022/10/14 08:55
@contact :   qqing_lai@hotmail.com
@company :   IMAOJIA Co,Ltd
'''

# here put the import lib
import json
import time
import logging

from dbapp.models import AppInfo, KubernetesCluster

from common.ext_fun import get_datadict

logger = logging.getLogger('drf')


class DeploymentCheck(object):
    def __init__(self, cli, appinfo_obj: AppInfo, k8s: KubernetesCluster, tag=None, app_deploy_name=None):
        self.cli = cli
        self.appinfo_obj = appinfo_obj
        self.k8s = k8s
        self.tag = tag
        self.app_deploy_name = app_deploy_name
        self.check_police = get_datadict('DEPLOY_CHECK', 1) or {
            'count': 30, 'interval': 6}
        self.count = self.check_police.get('count', 30)
        self.wait = self.check_police.get('interval', 6)
        self.namespace = self.appinfo_obj.namespace
        self.api_version = k8s.version.get('apiversion', 'apps/v1')

    def check_deployment(self, check_count):
        """
        检查 k8s deploy 状态
        :param check_count: 检查次数
        :return:
        """
        check_count -= 1
        deployment = self.cli.fetch_deployment(
            self.app_deploy_name, self.namespace, self.api_version)
        if deployment.get('ecode', 200) > 399 or check_count < 0:
            check_desc = f"Kubernetes集群[{self.k8s.name}]: 应用{self.appinfo_obj.app.alias}[{self.app_deploy_name}]Deployment检测异常\n"
            return False, check_desc
        if all([
            deployment['message']['metadata'].get('annotations', None),
            deployment['message']['spec'].get('selector', None)
        ]):
            if deployment['message']['metadata']['annotations'].get('deployment.kubernetes.io/revision', None):
                return True, deployment['message']
        time.sleep(1)
        return self.check_deployment(check_count)

    def check_replica(self, deployment, check_count, pod_status=None):
        """
        检测 rs 和pods， 判断是否就绪
        :return:
        """
        check_count -= 1
        if check_count < 0:
            # 如果超时了， 返回最后一次循环最后一个pod的状态信息
            check_desc = f"Kubernetes集群[{self.k8s.name}]: 应用{self.appinfo_obj.app.alias}[{self.app_deploy_name}] 未能在规定的时间内就绪，状态检测超时\n请查看Kubernetes Pod日志\n"
            return False, check_desc, pod_status
        labels = f"status-app-name-for-ops-platform={deployment['spec']['template']['metadata']['labels']['status-app-name-for-ops-platform']}"
        ret = self.cli.get_replica(
            self.namespace, self.api_version, **{"label_selector": labels})
        if ret.get('ecode', 200) > 399:
            check_desc = f"Kubernetes集群[{self.k8s.name}]: 应用{self.appinfo_obj.app.alias}[{self.app_deploy_name}]访问rs信息异常\n"
            return False, check_desc, ret

        rs_message = ret['message']
        if len(rs_message['items']) == 0 and check_count > 0:
            time.sleep(1)
            logger.debug('休眠1秒后继续查询replica')
            return self.check_replica(deployment, check_count)

        _key = 'deployment.kubernetes.io/revision'
        rs_list = [i for i in rs_message['items'] if
                   i['metadata']['annotations'][_key] == deployment['metadata']['annotations'][_key]]
        if not rs_list:
            return self.check_replica(deployment, check_count)
        rs = rs_list[0]
        if self.tag:
            try:
                image = rs['spec']['template']['spec']['containers'][0]['image']
                if image.split(':')[-1] != self.tag:
                    logger.debug('当前镜像版本和部署版本不一致')
                    return False, '部署状态检测结果: 当前运行版本和部署版本不一致，请查看Kubernetes Pod日志', {
                        '当前运行版本': image,
                        '部署版本': self.tag
                    }
            except BaseException as e:
                logger.exception(f"运行版本和部署版本检测发生异常 {e.__class__} {e} ")

        rs_status = rs['status']
        available_replicas = rs_status.get('availableReplicas', 0)
        fully_labeled_replicas = rs_status.get('fullyLabeledReplicas', 0)
        ready_replicas = rs_status.get('readyReplicas', 0)
        rs_ready_conditions = [
            available_replicas,
            fully_labeled_replicas,
            ready_replicas,
        ]
        rs_labels = ','.join(
            [f'{k}={v}' for k, v in rs['spec']['selector']['matchLabels'].items()])
        # 结合 rs 副本状态 和 pods 的状态， 只要 rs和其中一个pods完全就绪， 就算通过
        pods_ret = self.cli.get_pods(
            self.namespace, **{"label_selector": rs_labels})
        pod_list = pods_ret['message']['items']
        for pod in pod_list:
            pod_status = pod['status']
            if all(rs_ready_conditions) and pod_status['phase'].lower() == 'running' and (
                    'containerStatuses' in pod_status and
                    pod_status['containerStatuses'][0]['ready'] is True and
                    'running' in pod_status['containerStatuses'][0]['state']
            ):
                check_desc = f"{pod['metadata']['name']}\n 部署状态检测结果：当前Replica运行副本\n  - availableReplicas: {rs_status.get('availableReplicas', 0)}\n  - fullyLabeledReplicas: {rs_status.get('fullyLabeledReplicas', 0)}\n  - readyReplicas: {rs_status.get('readyReplicas', 0)}\n"
                return True, check_desc, pod_status

        return self.check_replica(deployment, check_count, pod_status)

    def run(self):
        is_ok, deployment = self.check_deployment(5)
        if not is_ok:
            return {'status': 2, 'message': deployment, 'data': deployment}

        desc = ''
        log = {}
        while True:
            self.count -= 1
            is_ok, desc, log = self.check_replica(deployment, 10)
            if is_ok:
                logger.info(
                    f"Kubernetes集群[{self.k8s.name}]: 应用{self.appinfo_obj.app.alias}[{self.appinfo_obj.app.name}]检测成功\n")
                return {'status': 1, 'message': desc, 'data': json.dumps(log)}
            if self.count < 0:
                break
            time.sleep(self.wait)
        return {'status': 2, 'message': desc, 'data': json.dumps(log)}


def deployment_check(cli, appinfo_obj: AppInfo, k8s: KubernetesCluster, tag=None, app_deploy_name=None):
    if not app_deploy_name:
        app_deploy_name = appinfo_obj.app.name
    dc = DeploymentCheck(cli, appinfo_obj, k8s, tag=tag,
                         app_deploy_name=app_deploy_name)
    return dc.run()
