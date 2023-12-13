#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
@Author : Charles Lai
@Contact : qqing_lai@hotmail.com
@Time : 2020/9/29 下午3:03
@FileName: serializers.py
@Blog ：https://imaojia.com
"""
import json

from dbapp.model.model_cmdb import Environment, MicroApp
from common.ext_fun import get_datadict
from django.db import transaction
from rest_framework import serializers
from dbapp.models import AppInfo
from dbapp.model.model_deploy import BuildJob, PublishOrder, PublishApp, DockerImage, DeployJob, \
    DeployJobResult, BuildJobResult

from common.extends.serializers import ModelSerializer, EsSerializer

import datetime
import shortuuid


class DockerImageSerializer(ModelSerializer):
    deployer_info = serializers.SerializerMethodField()

    def get_deployer_info(self, instance):
        return {'id': instance.deployer.id, 'username': instance.deployer.username,
                'first_name': instance.deployer.first_name}

    class Meta:
        model = DockerImage
        fields = '__all__'


class DeployJobListSerializer(ModelSerializer):
    deployer_info = serializers.SerializerMethodField()

    def get_deployer_info(self, instance):
        if instance.deployer:
            return {'id': instance.deployer.id, 'name': instance.deployer.name, 'position': instance.deployer.position}
        return {}

    class Meta:
        model = DeployJob
        fields = '__all__'


class ListForCicdSerializer(ModelSerializer):
    appinfo_obj_info = serializers.SerializerMethodField()
    environment = serializers.SerializerMethodField()
    environment_info = serializers.SerializerMethodField()
    project_info = serializers.SerializerMethodField()
    product_info = serializers.SerializerMethodField()
    deployer_info = serializers.SerializerMethodField()

    @staticmethod
    def instance_app(appinfo_id):
        return AppInfo.objects.get(id=appinfo_id)

    def get_deployer_info(self, instance):
        if instance.deployer:
            return {'id': instance.deployer.id, 'name': instance.deployer.name, 'position': instance.deployer.position}
        else:
            return {}

    def get_appinfo_obj_info(self, instance):
        try:
            appinfo_obj = self.instance_app(instance.appinfo_id)
            return {'appid': appinfo_obj.app.appid, 'name': appinfo_obj.app.name, 'alias': appinfo_obj.app.alias,
                    'category': get_datadict(appinfo_obj.app.category),
                    'environment': {'id': appinfo_obj.environment.id, 'name': appinfo_obj.environment.name,
                                    'alias': appinfo_obj.environment.alias}}
        except:
            return {}

    def get_environment(self, instance):
        try:
            appinfo_obj = self.instance_app(instance.appinfo_id)
            return appinfo_obj.environment.id
        except:
            return None

    def get_environment_info(self, instance):
        try:
            appinfo_obj = self.instance_app(instance.appinfo_id)
            return {'id': appinfo_obj.environment.id, 'name': appinfo_obj.environment.name,
                    'alias': appinfo_obj.environment.alias}
        except:
            return {}

    def get_project_info(self, instance):
        try:
            appinfo_obj = self.instance_app(instance.appinfo_id)
            return {'id': appinfo_obj.app.project.id, 'name': appinfo_obj.app.project.name,
                    'alias': appinfo_obj.app.project.alias}
        except:
            return {}

    def get_product_info(self, instance):
        try:
            appinfo_obj = self.instance_app(instance.appinfo_id)
            return {'id': appinfo_obj.app.project.product.id, 'name': appinfo_obj.app.project.product.name,
                    'alias': appinfo_obj.app.project.product.alias}
        except:
            return {}


class DeployJobInfoSerializer(ListForCicdSerializer):
    """
    ElasticSearch索引文档序列化
    """

    class Meta:
        model = DeployJob
        fields = '__all__'


class DeployJobSerializer(ModelSerializer):
    class Meta:
        model = DeployJob
        fields = '__all__'
        read_only_fields = ('uniq_id', 'status')


class BuildJobListSerializer(ModelSerializer):
    deployer_info = serializers.SerializerMethodField()

    def get_deployer_info(self, instance):
        if instance.deployer:
            return {'id': instance.deployer.id, 'first_name': instance.deployer.first_name, 'username': instance.deployer.username, 'name': instance.deployer.name, 'position': instance.deployer.position}
        return {}

    class Meta:
        model = BuildJob
        fields = '__all__'


class BuildJobEsListSerializer(EsSerializer, ListForCicdSerializer):
    """
    ElasticSearch索引文档序列化
    """

    class Meta:
        model = BuildJob
        fields = '__all__'


class DeployJobListForRollbackSerializer(BuildJobListSerializer):
    commits = serializers.SerializerMethodField('get_commits')
    commit_tag = serializers.SerializerMethodField()
    build_number = serializers.IntegerField()

    def get_commits(self, instance):
        try:
            return json.loads(instance.commits)
        except BaseException as e:
            return {}

    def get_commit_tag(self, instance):
        try:
            return json.loads(instance.commit_tag)
        except BaseException as e:
            return {}

    class Meta:
        model = DeployJob
        fields = '__all__'


class DeployJobEsListSerializer(EsSerializer, ListForCicdSerializer):
    """
    ElasticSearch索引文档序列化
    """

    class Meta:
        model = DeployJob
        fields = '__all__'


class BuildJobListForCiSerializer(BuildJobListSerializer):
    pass


class BuildJobSerializer(ModelSerializer):

    class Meta:
        model = BuildJob
        fields = '__all__'


class ResultSerializer(ModelSerializer):
    result = serializers.SerializerMethodField()

    def get_result(self, instance):
        try:
            result = json.loads(instance.result)
        except BaseException as e:
            result = {}
        return result


class DeployJobResultSerializer(ResultSerializer):
    class Meta:
        model = DeployJobResult
        fields = '__all__'


class BuildJobResultSerializer(ResultSerializer):
    class Meta:
        model = BuildJobResult
        fields = '__all__'
