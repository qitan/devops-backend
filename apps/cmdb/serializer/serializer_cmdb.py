#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
@Author : Charles Lai
@Contact : qqing_lai@hotmail.com
@Time : 2021/05/13 下午3:50
@FileName: serializer_cmdb
@Blog : https://imaojia.com
"""
from functools import reduce
from typing import OrderedDict, List
from django.core.cache import cache
from django.db.models import fields, Q
from rest_framework import serializers
from rest_framework.utils import html, model_meta
from django.db import transaction
from elasticsearch_dsl import Q as EQ

from dbapp.models import *
from common.ext_fun import get_datadict, get_deploy_image_list
from dbapp.model.model_deploy import BuildJob, BuildJobResult, DeployJob, DockerImage

from common.extends.serializers import ModelSerializer
from common.recursive import RecursiveField

import json
import logging

logger = logging.getLogger('drf')


class DevLanguageSerializers(ModelSerializer):
    class Meta:
        model = DevLanguage
        fields = '__all__'


class RegionSerializers(ModelSerializer):
    class Meta:
        model = Region
        fields = '__all__'


class ProductSerializers(ModelSerializer):
    children = RecursiveField(
        read_only=True, required=False, allow_null=True, many=True)
    region_info = serializers.SerializerMethodField()
    managers_info = serializers.SerializerMethodField()

    def get_region_info(self, instance):
        try:
            return {'name': instance.region.name, 'alias': instance.region.alias}
        except:
            return {'name': '', 'alias': ''}

    def get_managers_info(self, instance):
        info = {}
        for k, v in instance.managers.items():
            try:
                user = UserProfile.objects.get(id=v)
                info[k] = {'id': v, 'username': user.username,
                           'first_name': user.first_name}
            except:
                info[k] = {}
        return info

    class Meta:
        model = Product
        fields = '__all__'


class ProductWithProjectsSerializers(ProductSerializers):
    projects = serializers.SerializerMethodField()

    def get_projects(self, instance):
        projects = instance.project_set.all()
        return [{'id': i.id, 'name': i.name, 'alias': i.alias} for i in projects]

    class Meta:
        model = Product
        fields = '__all__'


class RegionProductSerializers(ModelSerializer):
    product = ProductSerializers(many=True, source='product_set')

    class Meta:
        model = Region
        fields = '__all__'


class EnvironmentSerializers(ModelSerializer):

    class Meta:
        model = Environment
        fields = '__all__'


class KubernetesClusterDescSerializers(ModelSerializer):
    class Meta:
        model = KubernetesCluster
        fields = ('id', 'name', 'desc')


class KubernetesClusterListSerializers(ModelSerializer):
    config = serializers.SerializerMethodField()

    def get_config(self, instance):
        return json.loads(instance.config)

    class Meta:
        model = KubernetesCluster
        fields = '__all__'


class KubernetesClusterSerializers(ModelSerializer):
    class Meta:
        model = KubernetesCluster
        fields = '__all__'


class ProjectConfigSerializers(ModelSerializer):

    class Meta:
        model = ProjectConfig
        fields = '__all__'


class ProjectEnvReleaseConfigSerializers(ModelSerializer):
    class Meta:
        model = ProjectEnvReleaseConfig
        fields = '__all__'


class ProjectListSerializers(ModelSerializer):
    children = RecursiveField(
        read_only=True, required=False, allow_null=True, many=True)
    manager_info = serializers.SerializerMethodField()
    developer_info = serializers.SerializerMethodField()

    @staticmethod
    def user_query(id):
        user = UserProfile.objects.filter(id=id)
        if user:
            return user[0]
        return None

    def get_manager_info(self, instance):
        user = self.user_query(instance.manager)
        if user:
            return {'id': user.id, 'first_name': user.first_name, 'username': user.username}
        return {}

    def get_developer_info(self, instance):
        user = self.user_query(instance.developer)
        if user:
            return {'id': user.id, 'first_name': user.first_name, 'username': user.username}
        return {}

    class Meta:
        model = Project
        fields = '__all__'


class ProjectSerializers(ModelSerializer):

    class Meta:
        model = Project
        fields = '__all__'
        read_only_fields = ('projectid',)

    @staticmethod
    def perform_extend_save(validated_data):
        _prefix = 'default'

        if validated_data.get('parent', None):
            _prefix = validated_data['parent'].name
        else:
            if validated_data.get('product', None):
                _prefix = validated_data['product'].name
        if validated_data.get('name', None):
            validated_data['projectid'] = f"{_prefix}.{validated_data['name']}"

        return validated_data

    def create(self, validated_data):
        instance = Project.objects.create(
            **self.perform_extend_save(validated_data))
        return instance

    def update(self, instance, validated_data):
        validated_data = self.perform_extend_save(validated_data)
        serializers.raise_errors_on_nested_writes(
            'update', self, validated_data)
        info = model_meta.get_field_info(instance)

        # Simply set each attribute on the instance, and then save it.
        # Note that unlike `.create()` we don't need to treat many-to-many
        # relationships as being a special case. During updates we already
        # have an instance pk for the relationships to be associated with.
        m2m_fields = []
        for attr, value in validated_data.items():
            if attr in info.relations and info.relations[attr].to_many:
                m2m_fields.append((attr, value))
            else:
                setattr(instance, attr, value)

        instance.save()

        # Note that many-to-many fields are set after updating instance.
        # Setting m2m fields triggers signals which could potentially change
        # updated instance and we do not want it to collide with .update()
        for attr, value in m2m_fields:
            field = getattr(instance, attr)
            field.set(value)

        return instance


class MicroAppListForPermApplySerializers(ModelSerializer):
    class Meta:
        model = MicroApp
        fields = ('id', 'appid', 'name', 'alias')


class MicroAppListSerializers(ModelSerializer):
    project_info = serializers.SerializerMethodField()
    product_info = serializers.SerializerMethodField()
    appinfo = serializers.SerializerMethodField()
    creator_info = serializers.SerializerMethodField()
    related_apps = serializers.SerializerMethodField()
    env_app = serializers.SerializerMethodField()
    team_members = serializers.SerializerMethodField()

    def get_team_members(self, instance):
        members = {}
        for k, v in instance.team_members.items():
            members[k] = [{'id': i.id, 'name': i.name, 'username': i.username}
                          for i in UserProfile.objects.filter(id__in=v)]
        return members

    def get_project_info(self, instance):
        return {'id': instance.project.id, 'alias': instance.project.alias}

    def get_product_info(self, instance):
        return {'id': instance.project.product.id, 'alias': instance.project.product.alias}

    def get_appinfo(self, instance):
        return [
            {'id': i.id, 'env_alias': i.environment.alias, 'env': {'name': i.environment.name, 'id': i.environment.id},
             } for i in instance.appinfo_set.all()]

    def get_creator_info(self, instance):
        try:
            return {'id': instance.creator.id, 'first_name': instance.creator.first_name,
                    'username': instance.creator.username}
        except BaseException as e:
            logger.info(f'获取不到应用{instance.appid}创建者信息')
            return {'id': '', 'first_name': '', 'username': ''}

    def get_related_apps(self, instance):
        if instance.multiple_app:
            qs = MicroApp.objects.filter(id__in=instance.multiple_ids)
            return [{'id': i.id, 'appid': i.appid, 'name': i.name, 'alias': i.alias} for i in qs]
        return []

    def get_env_app(self, instance):
        return {i.environment.id: {
            'env': {'alias': i.environment.alias, 'name': i.environment.name, 'id': i.environment.id},
            'appinfo': {'id': i.id}} for i in instance.appinfo_set.all()}

    class Meta:
        model = MicroApp
        fields = '__all__'


class MicroAppSerializers(ModelSerializer):
    class Meta:
        model = MicroApp
        fields = '__all__'
        read_only_fields = ('appid',)

    @staticmethod
    def perform_extend_save(validated_data):
        def default_value(fields: List):
            for field in fields:
                if validated_data.get(field):
                    if validated_data[field].get('key') != 'custom':
                        validated_data[field]['value'] = validated_data[field]['key']
            return validated_data

        validated_data = default_value(['dockerfile', 'target'])
        # 成员去重
        if validated_data.get('team_members', []):
            data = {}
            for k, v in validated_data['team_members'].items():
                _d = False
                for i in v:
                    if isinstance(i, (dict, )):
                        _d = True
                        break
                if _d:
                    v = [i['id'] for i in v]
                data[k] = list(set(v))
            validated_data['team_members'] = data
        if validated_data.get('project', None) and validated_data.get('name', None):
            validated_data[
                'appid'] = f"{validated_data['project'].product.name}.{validated_data['project'].name}.{validated_data['name']}"
        return validated_data

    def create(self, validated_data):
        instance = MicroApp.objects.create(can_edit=[validated_data['creator'].id],
                                           **self.perform_extend_save(validated_data))
        return instance

    def update(self, instance, validated_data):
        return super().update(instance, self.perform_extend_save(validated_data))


class KubernetesDeploySerializers(ModelSerializer):
    kubernetes = KubernetesClusterDescSerializers()

    class Meta:
        model = KubernetesDeploy
        fields = '__all__'


class AppInfoListForCiSerializers(ModelSerializer):
    app = serializers.SerializerMethodField()
    last_build = serializers.SerializerMethodField()
    last_deploy = serializers.SerializerMethodField()
    namespace = serializers.SerializerMethodField()
    kubernetes_info = serializers.SerializerMethodField()

    def get_namespace(self, instance):
        return instance.namespace

    def get_app(self, instance):
        return {'id': instance.app.id, 'appid': instance.app.appid, 'name': instance.app.name,
                'alias': instance.app.alias, 'project': instance.app.project.alias,
                'product': instance.app.project.product.alias, 'category': instance.app.category,
                'language': instance.app.language, 'repo': instance.app.repo,
                'desc': instance.app.desc,
                'is_k8s': instance.app.is_k8s,
                'modules': instance.app.modules}

    def get_last_build(self, instance):
        objs = BuildJob.objects.filter(appinfo_id=instance.id)
        build = objs.first()
        job = {}
        if build:
            objs = objs.filter(batch_uuid=build.batch_uuid)
            batch_status = [i.status for i in objs]
            cache.set(f"{CI_LATEST_KEY}{instance.id}", build, None)
            _fields = ('created_time', 'id', 'order_id', 'status',
                       'build_number', 'commit_tag', 'commits', 'image')
            for f in _fields:
                job[f] = build.__dict__.get(f)
            if 3 in batch_status:
                job['status'] = 3
            job['type'] = 'ci'
            job['result'] = {}
            try:
                if build.status == 3:
                    # 构建中
                    pass
                else:
                    job['result'] = BuildJobResult.objects.defer(
                        'console_output').filter(job_id=build.id).first().result
                    if isinstance(job['result'], (str, )):
                        job['result'] = json.loads(job['result'])
            except BaseException as e:
                logger.debug(f'获取{build.id}结果失败，原因：{e}')
            job['deployer'] = {}
            try:
                if build.deployer:
                    job['deployer'] = {'id': build.deployer.id, 'username': build.deployer.username,
                                       'first_name': build.deployer.first_name, 'position': build.deployer.position}
            except BaseException as e:
                logger.debug(f"查询deployer失败, 原因: {e}")
        return job

    def get_last_deploy(self, instance):
        objs = DeployJob.objects.filter(appinfo_id=instance.id)
        build = objs.first()
        job = {}
        if build:
            objs = objs.filter(batch_uuid=build.batch_uuid)
            batch_status = [i.status for i in objs]
            cache.set(f"{CD_LATEST_KEY}{instance.id}", build, None)
            _fields = ('created_time', 'id', 'order_id',
                       'status', 'image', 'batch_uuid')
            for f in _fields:
                job[f] = build.__dict__.get(f)
            if 3 in batch_status:
                job['status'] = 3
            job['type'] = 'cd'
            job['deployer'] = {}
            try:
                if build.deployer:
                    job['deployer'] = {'id': build.deployer.id, 'username': build.deployer.username,
                                       'first_name': build.deployer.first_name, 'position': build.deployer.position}
            except BaseException as e:
                logger.exception(f"查询deployer异常, 原因: {e}")
        return job

    def get_kubernetes_info(self, instance):
        serializer = KubernetesDeploySerializers(
            data=KubernetesDeploy.objects.filter(appinfo=instance.id), many=True)
        serializer.is_valid()
        return serializer.data

    class Meta:
        model = AppInfo
        exclude = ('template', 'can_edit', 'build_command')


class AppInfoListForCdSerializers(AppInfoListForCiSerializers):
    kubernetes_info = serializers.SerializerMethodField()

    def get_last_build(self, instance):
        objs = DeployJob.objects.filter(appinfo_id=instance.id)
        build = objs.first()
        job = {}
        if build:
            objs = objs.filter(batch_uuid=build.batch_uuid)
            batch_status = [i.status for i in objs]
            cache.set(f"{CD_LATEST_KEY}{instance.id}", build, None)
            _fields = ('created_time', 'id', 'order_id',
                       'status', 'image', 'batch_uuid')
            for f in _fields:
                job[f] = build.__dict__.get(f)
            if 3 in batch_status:
                job['status'] = 3
            job['type'] = 'cd'
            job['deployer'] = {}
            try:
                if build.deployer:
                    job['deployer'] = {'id': build.deployer.id, 'username': build.deployer.username,
                                       'first_name': build.deployer.first_name, 'position': build.deployer.position}
            except BaseException as e:
                logger.exception(f"查询deployer异常, 原因: {e}")
        return job

    def get_kubernetes_info(self, instance):
        serializer = KubernetesDeploySerializers(
            data=KubernetesDeploy.objects.filter(appinfo=instance.id), many=True)
        serializer.is_valid()
        return serializer.data


class AppInfoListForOrderSerializers(AppInfoListForCdSerializers):

    def get_app(self, instance):
        return {'id': instance.app.id, 'appid': instance.app.appid, 'name': instance.app.name,
                'alias': instance.app.alias, 'project': instance.app.project.alias,
                'product': instance.app.project.product.alias, 'category': instance.app.category,
                'is_k8s': instance.app.is_k8s, 'modules': instance.app.modules}

    def get_last_build(self, instance):
        pass

    class Meta:
        model = AppInfo
        fields = ('id', 'app', 'uniq_tag')


class AppInfoListForDeploySerializers(AppInfoListForCdSerializers):
    image = serializers.SerializerMethodField()

    def get_app(self, instance):
        return {'id': instance.app.id, 'appid': instance.app.appid, 'name': instance.app.name,
                'alias': instance.app.alias, 'project': instance.app.project.alias,
                'product': instance.app.project.product.alias, 'category': instance.app.category,
                'language': instance.app.language, 'repo': instance.app.repo,
                'desc': instance.app.desc, 'is_k8s': instance.app.is_k8s, 'modules': instance.app.modules}

    def get_image(self, instance):
        images = get_deploy_image_list(instance.app_id, instance.id)
        if images and len(images):
            return {'id': images[0].id, 'appinfo_id': images[0].appinfo_id, 'commits': images[0].commits,
                    'commit_tag': images[0].commit_tag, 'status': images[0].status, 'image': images[0].image}
        return {'image': None, 'commits': {}}


class AppInfoListSerializers(ModelSerializer):
    app = MicroAppSerializers()
    kubernetes_info = serializers.SerializerMethodField()

    def get_kubernetes_info(self, instance):
        serializer = KubernetesDeploySerializers(
            data=KubernetesDeploy.objects.filter(appinfo=instance.id), many=True)
        serializer.is_valid()
        return serializer.data

    class Meta:
        model = AppInfo
        fields = '__all__'


class AppInfoSerializers(ModelSerializer):
    class Meta:
        model = AppInfo
        fields = '__all__'

    def perform_extend_save(self, validated_data, *args, **kwargs):
        if validated_data.get('app', None) and validated_data.get('environment', None):
            validated_data[
                'uniq_tag'] = f"{validated_data['app'].appid}.{validated_data['environment'].name.split('_')[-1].lower()}"

        if kwargs.get('instance', None):
            if "kubernetes" in self.initial_data:
                kubernetes = self.initial_data.get('kubernetes')
                _bulk = []
                for kid in kubernetes:
                    _ks = KubernetesCluster.objects.get(id=kid)
                    _bulk.append(KubernetesDeploy(
                        appinfo=kwargs['instance'], kubernetes=_ks))
                KubernetesDeploy.objects.bulk_create(
                    _bulk, ignore_conflicts=True)
        return validated_data

    @transaction.atomic
    def create(self, validated_data):
        instance = AppInfo.objects.create(
            **self.perform_extend_save(validated_data))
        if "kubernetes" in self.initial_data:
            self.perform_extend_save(validated_data, **{'instance': instance})
        return instance

    @transaction.atomic
    def update(self, instance, validated_data):
        if "kubernetes" in self.initial_data:
            KubernetesDeploy.objects.filter(appinfo=instance).delete()
        instance.__dict__.update(
            **self.perform_extend_save(validated_data, **{'instance': instance}))
        instance.save()
        return instance
