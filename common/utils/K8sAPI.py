#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
@Author : Charles Lai
@Contact : qqing_lai@hotmail.com
@Time : 2020/10/27 下午3:35
@FileName: K8sAPI.py
@Blog ：https://imaojia.com
"""
import kubernetes.client
from kubernetes import client, config, watch
from kubernetes.client import ApiClient, ApiException, api_client
from kubernetes.client.apis import core_v1_api
from kubernetes.stream import stream

from urllib.parse import urlencode
from ruamel import yaml
from datetime import datetime
import json
import operator
import logging
from typing import AnyStr, List, Dict, Type

logger = logging.getLogger(__name__)


class K8sAPI(object):
    def __init__(self, host=None, username=None, password=None, api_key=None, api_key_prefix='Bearer', verify_ssl=False,
                 k8s_config=None,
                 config_file=None, eks=None):
        """
        elk: aws kubernetes
        """
        self.__host = host
        self.__username = username
        self.__password = password
        self.__api_key = api_key
        self.__api_key_prefix = api_key_prefix
        self.__verify_ssl = verify_ssl
        if k8s_config is not None:
            config.kube_config.load_kube_config_from_dict(k8s_config)
            self.__client0 = client.CoreApi()
            self.__client = client.CoreV1Api()
        elif config_file is not None:
            config.kube_config.load_kube_config(config_file=config_file)
            self.__client0 = client.CoreApi()
            self.__client = client.CoreV1Api()
        elif self.__host:
            if self.__username and self.__password:
                self.__client = self.get_api()
            else:
                raise Exception('Please input username/password or api_key')
        else:
            raise Exception('Cannot find k8s config')
        self.client = self.__client

    def get_token(self):
        pass

    def get_api(self):
        configuration = client.Configuration()
        configuration.host = self.__host
        if self.__verify_ssl is False:
            configuration.verify_ssl = False
        configuration.username = self.__username
        configuration.password = self.__password
        basic_auth_token = configuration.get_basic_auth_token()
        api = core_v1_api.CoreV1Api(api_client.ApiClient(configuration=configuration, header_name="authorization",
                                                         header_value=basic_auth_token))
        return api

    def get_client(self):
        return self.__client

    def set_client(self, obj):
        self.__client = getattr(client, obj)()

    def get_apis(self):
        print("Supported APIs (* is preferred version):")
        self.__client2 = client.ApisApi(self.__client0.api_client)
        for api in self.__client2.get_api_versions().groups:
            versions = []
            for v in api.versions:
                name = ""
                if v.version == api.preferred_version.version and len(
                        api.versions) > 1:
                    name += "*"
                name += v.version
                versions.append(name)

    def get_nodes(self, **kwargs):
        ret = self.__client.list_node(**kwargs)
        try:
            rs = ApiClient().sanitize_for_serialization(ret)
            return rs
        except BaseException as e:
            return {'err': str(e)}

    def get_node_info(self, name):
        ret = self.__client.read_node_status(name)
        try:
            rs = ApiClient().sanitize_for_serialization(ret)
            return rs
        except BaseException as e:
            return {'err': str(e)}

    def get_namespaces(self, **kwargs):
        ret = self.__client.list_namespace(**kwargs)
        try:
            rs = ApiClient().sanitize_for_serialization(ret)
            return rs
        except BaseException as e:
            return {'err': str(e)}

    def create_namespace(self, name):
        payload = {
            "apiVersion": "v1",
            "kind": "Namespace",
            "metadata": {
                "name": name,
            }
        }
        ret = self.__client.create_namespace(body=payload)
        try:
            rs = ApiClient().sanitize_for_serialization(ret)
            print(rs)
            return rs
        except BaseException as e:
            return {'err': str(e)}

    def get_services(self, namespace='default', **kwargs):
        ret = self.__client.list_namespaced_service(namespace, **kwargs)
        try:
            rs = ApiClient().sanitize_for_serialization(ret)
            return rs
        except BaseException as e:
            return {'err': str(e)}

    def fetch_service(self, name, namespace='default', api_version='apps/v1'):
        try:
            ret = self.__client.read_namespaced_service(name, namespace)
            try:
                rs = ApiClient().sanitize_for_serialization(ret)
                return {'ecode': 200, 'message': rs}
            except BaseException as e:
                print('reason', e.reason)
                return {'ecode': e.status, 'message': e.body}
        except BaseException as e:
            print('reason', e.reason)
            return {'ecode': e.status, 'message': e.body}

    def create_namespace_service(self, name, app=None, targets=list, namespace='default', service_type='NodePort',
                                 svc_yaml=None):
        """
        目前只支持NodePort类型，对外服务端口随机生成（如手动生成，需配置node_port和endpoints）
        :param name: service name
        :param app: app name
        :param targets: [{port, target_port, protocol, node_port}]
        :param namespace:
        :param service_type:
        :return:
        """
        ports = []
        if svc_yaml:
            if isinstance(svc_yaml, str):
                body = yaml.safe_load(svc_yaml)
            else:
                body = svc_yaml
        else:
            for index, target in enumerate(targets):
                port_body = {'name': f"{name}-{index}", 'port': target['port'], 'target_port': target['port'],
                             'protocol': target['protocol']}
                if target['node_port'] > 30000:
                    port_body['node_port'] = target['node_port']
                ports.append(client.V1ServicePort(**port_body))
            body = client.V1Service(
                api_version="v1",
                kind="Service",
                metadata=client.V1ObjectMeta(
                    name=name
                ),
                spec=client.V1ServiceSpec(
                    selector={"app": app},
                    type=service_type,
                    ports=ports
                )
            )
        try:
            ret = self.__client.create_namespaced_service(namespace=namespace, body=body,
                                                          **{'_return_http_data_only': False})
            try:
                rs = ApiClient().sanitize_for_serialization(ret)
                return {'ecode': 200, 'message': rs}
            except BaseException as e:
                logger.error('reason', e)
                return {'error': True, 'message': str(e)}
        except ApiException as e:
            if e.status == 409:
                logger.error('reason', e.reason)
            return {'error': True, 'ecode': e.status, 'message': e.body}
        except BaseException as e:
            return {'error': True, 'message': str(e)}

    def update_namespace_service(self, name, app=None, targets=Type[list], namespace='default', service_type='NodePort',
                                 svc_yaml=None):
        ports = []
        if svc_yaml:
            if isinstance(svc_yaml, str):
                body = yaml.safe_load(svc_yaml)
            else:
                body = svc_yaml
            logger.debug(f'svc_yaml body == {body}')
            func = self.__client.replace_namespaced_service
        else:
            for index, target in enumerate(targets):
                port_body = {'name': target['name'], 'port': target['port'], 'target_port': target['port'],
                             'protocol': target['protocol']}
                if target['node_port'] > 30000:
                    port_body['node_port'] = target['node_port']
                ports.append(client.V1ServicePort(**port_body))
            body = client.V1Service(
                api_version="v1",
                kind="Service",
                metadata=client.V1ObjectMeta(
                    name=name
                ),
                spec=client.V1ServiceSpec(
                    selector={"app": name},
                    type=service_type,
                    ports=ports
                )
            )
            func = self.__client.patch_namespaced_service
        try:
            ret = func(
                name, namespace, body=body,
                **{'_return_http_data_only': False}
            )
            try:
                rs = ApiClient().sanitize_for_serialization(ret)
                return {'ecode': 200, 'message': rs}
            except BaseException as e:
                logger.error(f'ApiClient sanitize_for_serialization 异常： {e}', )
                return {'error': True, 'message': str(e)}
        except ApiException as e:
            if e.status == 409:
                logger.error(f'ApiException 异常 409 资源冲突： {e} {e.reason}', )
            return {'error': True, 'ecode': e.status, 'message': e.body}
        except BaseException as e:
            logger.error(f'patch_namespaced_service 异常： {e}', )
            return {'error': True, 'message': str(e)}

    def delete_namespace_service(self, name, namespace='default', api_version='apps/v1'):
        try:
            ret = self.__client.delete_namespaced_service(name, namespace)
            rs = ApiClient().sanitize_for_serialization(ret)
            return {'ecode': 200, 'message': rs}
        except BaseException as e:
            return {'error': True, 'message': str(e)}

    def get_configmaps(self, namespace='default', **kwargs):
        ret = self.__client.list_namespaced_config_map(namespace, **kwargs)
        try:
            rs = ApiClient().sanitize_for_serialization(ret)
            return rs
        except BaseException as e:
            return {'error': True, 'message': str(e)}

    def get_configmap(self, name, namespace='default', **kwargs):
        """
        get configmap content
        """
        try:
            ret = self.__client.read_namespaced_config_map(
                name, namespace, **kwargs)
            rs = ApiClient().sanitize_for_serialization(ret)
            return rs
        except BaseException as e:
            return {'error': True, 'message': str(e)}

    def create_namespace_configmap(self, svc_yaml, namespace='default', **kwargs):
        if isinstance(svc_yaml, str):
            body = yaml.safe_load(svc_yaml)
        else:
            body = svc_yaml
        try:
            ret = self.__client.create_namespaced_config_map(
                namespace, body, **kwargs)
            rs = ApiClient().sanitize_for_serialization(ret)
            return {'ecode': 200, 'message': rs}
        except BaseException as e:
            return {'error': True, 'message': str(e)}

    def update_namespace_configmap(self, name, svc_yaml, namespace='default', **kwargs):
        if isinstance(svc_yaml, str):
            body = yaml.safe_load(svc_yaml)
        else:
            body = svc_yaml
        try:
            ret = self.__client.patch_namespaced_config_map(
                name, namespace, body, **kwargs)
            rs = ApiClient().sanitize_for_serialization(ret)
            return {'ecode': 200, 'message': rs}
        except BaseException as e:
            return {'error': True, 'message': str(e)}

    def delete_namespace_configmap(self, name, namespace='default', api_version='apps/v1'):
        try:
            ret = self.__client.delete_namespaced_config_map(name, namespace)
            rs = ApiClient().sanitize_for_serialization(ret)
            return {'ecode': 200, 'message': rs}
        except BaseException as e:
            return {'error': True, 'message': str(e)}

    def get_namespace_deployment(self, namespace='default', api_version='apps/v1', **kwargs):
        self.__client2 = operator.methodcaller(''.join([i.capitalize() for i in api_version.split('/')]) + 'Api',
                                               self.__client.api_client)(client)
        ret = self.__client2.list_namespaced_deployment(namespace, **kwargs)
        try:
            rs = ApiClient().sanitize_for_serialization(ret)
            return rs
        except BaseException as e:
            return {'err': str(e)}

    def create_namespace_deployment(self, name, image=None, port=list, replicas=1, deploy_yaml=None,
                                    pod_type='Deployment', namespace='default'):
        """

        :param name:
        :param image:
        :param port: [{containerPort: 8080, protocol: 'TCP'}]
        :param replicas:
        :param pod_type:
        :param namespace:
        :return:
        """
        payload = {'kind': pod_type, 'spec': {'replicas': replicas, 'template': {
            'spec': {'containers': [{'image': image, 'name': name, 'ports': port}]},
            'metadata': {'labels': {'app': name}}},
            'selector': {'matchLabels': {'app': name}}},
            'apiVersion': 'apps/v1beta2',
            'metadata': {'labels': {'app': name}, 'namespace': namespace,
                         'name': name}}
        if deploy_yaml is not None:
            payload = yaml.safe_load(deploy_yaml)
            payload['metadata'].pop('resourceVersion', None)
        self.__client2 = operator.methodcaller(
            ''.join([i.capitalize() for i in payload.get(
                'apiVersion', 'apps/v1beta2').split('/')]) + 'Api',
            self.__client.api_client)(client)
        try:
            ret = self.__client2.create_namespaced_deployment(
                namespace=namespace, body=payload)
            try:
                rs = ApiClient().sanitize_for_serialization(ret)
                return {'ecode': 200, 'message': rs}
            except BaseException as e:
                return {'ecode': e.status, 'message': e.body}
        except ApiException as e:
            return {'ecode': e.status, 'message': e.body}

    def delete_namespace_deployment(self, name, namespace='default', api_version='apps/v1'):
        self.__client2 = operator.methodcaller(''.join([i.capitalize() for i in api_version.split('/')]) + 'Api',
                                               self.__client.api_client)(client)
        ret = self.__client2.delete_namespaced_deployment(name, namespace,
                                                          body=client.V1DeleteOptions(grace_period_seconds=0,
                                                                                      propagation_policy='Foreground'))
        try:
            rs = ApiClient().sanitize_for_serialization(ret)
            return rs
        except BaseException as e:
            return {'err': str(e)}

    def update_deployment(self, name, replicas=None, image=None, envs=None, deploy_yaml=None, namespace='default',
                          api_version='apps/v1', force=False):
        """
        force: 强制更新
        """
        self.__client2 = operator.methodcaller(''.join([i.capitalize() for i in api_version.split('/')]) + 'Api',
                                               self.__client.api_client)(client)
        payload = {'spec': {'replicas': replicas, 'template': {}}}
        if replicas is None and image is None and deploy_yaml is None:
            return {'err': '缺少参数'}
        if replicas is not None:
            payload['spec']['replicas'] = replicas
        if image is not None:
            payload['spec']['template'] = {
                'spec': {'containers': [{'image': image, 'name': name}]}}

        if envs is not None:
            payload['spec']['template'] = {
                'spec': {'containers': [{'env': envs}]}}

        if deploy_yaml is not None:
            payload = yaml.safe_load(deploy_yaml)
            payload['metadata'].pop('resourceVersion', None)
        try:
            if force:
                ret = self.__client2.replace_namespaced_deployment(
                    name, namespace, body=payload)
            else:
                ret = self.__client2.patch_namespaced_deployment(
                    name, namespace, body=payload)
            try:
                rs = ApiClient().sanitize_for_serialization(ret)
                return {'ecode': 200, 'message': rs}
            except BaseException as e:
                return {'ecode': e.status, 'message': e.body}
        except ApiException as e:
            return {'ecode': e.status, 'message': e.body}

    def update_deployment_replica(self, name, replicas, namespace='default', api_version='apps/v1'):
        self.__client2 = operator.methodcaller(''.join([i.capitalize() for i in api_version.split('/')]) + 'Api',
                                               self.__client.api_client)(client)
        payload = {'spec': {'replicas': replicas}}
        ret = self.__client2.patch_namespaced_deployment_scale(
            name, namespace, body=payload)
        try:
            rs = ApiClient().sanitize_for_serialization(ret)
            return rs
        except BaseException as e:
            return {'err': str(e)}

    def update_deployment_image(self, name, image, namespace='default', api_version='apps/v1'):
        deploy = self.fetch_deployment(name, namespace)
        if deploy.get('ecode', 200) > 399:
            return deploy
        payload = {'spec': deploy['message']['spec']}
        payload['spec']['template']['spec']['containers'][0]['image'] = image
        self.__client2 = operator.methodcaller(''.join([i.capitalize() for i in api_version.split('/')]) + 'Api',
                                               self.__client.api_client)(client)
        try:
            ret = self.__client2.patch_namespaced_deployment(name, namespace, body=payload,
                                                             **{'_return_http_data_only': False})
        except ApiException as e:
            return {'ecode': e.status, 'message': e.body}
        try:
            rs = ApiClient().sanitize_for_serialization(ret)
            return {'ecode': 200, 'message': rs}
        except BaseException as e:
            return {'ecode': e.status, 'message': e.body}

    def update_deployment_resource(self, name, envs, image_policy, namespace='default', api_version='apps/v1',
                                   **kwargs):
        payload = {'spec': {'template': {'spec': {'containers': [
            {'name': name, 'env': envs, 'imagePullPolicy': image_policy, 'resources': kwargs['resources']}]}}}}
        self.__client2 = operator.methodcaller(''.join([i.capitalize() for i in api_version.split('/')]) + 'Api',
                                               self.__client.api_client)(client)
        ret = self.__client2.patch_namespaced_deployment(
            name, namespace, body=payload)
        try:
            rs = ApiClient().sanitize_for_serialization(ret)
            return rs
        except BaseException as e:
            return {'err': str(e)}

    def restart_deployment(self, name, namespace='default', api_version='apps/v1'):
        self.__client2 = operator.methodcaller(''.join([i.capitalize() for i in api_version.split('/')]) + 'Api',
                                               self.__client.api_client)(client)
        payload = {
            'spec': {
                'template': {
                    'spec': {
                        'containers': [
                            {
                                'name': name,
                                'env': [
                                    {
                                        'name': 'RESTART_',
                                        'value': datetime.now().strftime('%Y%m%d%H%M%S')
                                    }
                                ]
                            }
                        ]
                    }
                }
            }
        }

        ret = self.__client2.patch_namespaced_deployment(
            name, namespace, body=payload)
        try:
            rs = ApiClient().sanitize_for_serialization(ret)
            return rs
        except BaseException as e:
            return {'err': str(e)}

    def fetch_deployment(self, name, namespace='default', api_version='apps/v1'):
        self.__client2 = operator.methodcaller(''.join([i.capitalize() for i in api_version.split('/')]) + 'Api',
                                               self.__client.api_client)(client)
        try:
            ret = self.__client2.read_namespaced_deployment(name, namespace)
            try:
                rs = ApiClient().sanitize_for_serialization(ret)
                return {'ecode': 200, 'message': rs}
            except ApiException as e:
                return {'ecode': e.status, 'message': e.body}
        except ApiException as e:
            return {'ecode': e.status, 'message': e.body}

    def get_replica(self, namespace='default', api_version='apps/v1', **kwargs):
        self.__client2 = operator.methodcaller(''.join([i.capitalize() for i in api_version.split('/')]) + 'Api',
                                               self.__client.api_client)(client)
        try:
            ret = self.__client2.list_namespaced_replica_set(
                namespace=namespace, **kwargs)
            try:
                rs = ApiClient().sanitize_for_serialization(ret)
                return {'ecode': 200, 'message': rs}
            except ApiException as e:
                return {'ecode': e.status, 'message': e.body}
        except ApiException as e:
            return {'ecode': e.status, 'message': e.body}

    def get_pods(self, namespace=None, **kwargs):
        if namespace is None:
            return {}
        try:
            ret = self.__client.list_namespaced_pod(namespace, **kwargs)
            try:
                rs = ApiClient().sanitize_for_serialization(ret)
                return {'ecode': 200, 'message': rs}
            except BaseException as e:
                return {'ecode': e.status, 'message': e.body}
        except ApiException as e:
            return {'ecode': e.status, 'message': e.body}

    def fetch_pod(self, name, namespace='default'):
        try:
            ret = self.__client.read_namespaced_pod(
                name=name, namespace=namespace)
            try:
                rs = ApiClient().sanitize_for_serialization(ret)
                return {'ecode': 200, 'message': rs}
            except BaseException as e:
                return {'ecode': e.status, 'message': e.body}
        except BaseException as e:
            return {'ecode': e.status, 'message': e.body}

    def get_secrets(self, namespace='default', **kwargs):
        ret = self.__client.list_namespaced_secret(namespace, **kwargs)
        try:
            rs = ApiClient().sanitize_for_serialization(ret)
            return rs
        except BaseException as e:
            return {'error': True, 'message': str(e)}

    def get_secret(self, name, namespace='default', **kwargs):
        """
        get secret content
        """
        ret = self.__client.read_namespaced_secret(name, namespace, **kwargs)
        try:
            ret = self.__client.read_namespaced_secret(
                name, namespace, **kwargs)
            rs = ApiClient().sanitize_for_serialization(ret)
            return rs
        except BaseException as e:
            return {'error': True, 'message': str(e)}

    def manage_secret(self, name, namespace='default', api_version='v1', **kwargs):
        payload = kwargs.pop('payload', {})
        body = kubernetes.client.V1Secret(api_version=api_version, **payload)
        ret = {}
        try:
            ret = self.__client.replace_namespaced_secret(
                name, namespace, body, **kwargs)
        except ApiException as e:
            if e.status == 404:
                ret = self.__client.create_namespaced_secret(namespace, body)
        try:
            rs = ApiClient().sanitize_for_serialization(ret)
            return rs
        except BaseException as e:
            return {'error': True, 'message': str(e)}
