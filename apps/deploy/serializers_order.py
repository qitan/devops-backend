#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
@Author : Charles Lai
@Contact : qqing_lai@hotmail.com
@Time : 2022/1/14 下午4:13
@FileName: serializers_order.py
@Blog ：https://imaojia.com
"""
from django.db import transaction
from rest_framework import serializers

from dbapp.models import Project
from common.ext_fun import template_generate
from dbapp.model.model_deploy import PublishOrder, PublishApp, DeployJob
from dbapp.models import AppInfo, Environment
from common.extends.serializers import ModelSerializer, EsSerializer

import shortuuid
import datetime

from deploy.ext_func import check_user_deploy_perm
from dbapp.model.model_workflow import Workflow, WorkflowNodeHistory


class PublishAppSerializer(ModelSerializer):
    last_build = serializers.SerializerMethodField()
    kubernetes = serializers.SerializerMethodField()
    hosts = serializers.SerializerMethodField()
    project_info = serializers.SerializerMethodField()
    product_info = serializers.SerializerMethodField()
    template = serializers.SerializerMethodField()
    is_k8s = serializers.SerializerMethodField()

    def get_last_build(self, instance):
        job = {}
        build = DeployJob.objects.filter(
            appinfo_id=instance.appinfo_id, order_id=instance.order_id).first()
        if build:
            _fields = ('created_time', 'id', 'order_id', 'status',
                       'build_number', 'commit_tag', 'commits', 'image')
            for f in _fields:
                job[f] = build.__dict__.get(f)
            job['type'] = 'ci'
            job['deployer'] = {}
            try:
                if build.deployer:
                    job['deployer'] = {'id': build.deployer.id, 'username': build.deployer.username,
                                       'first_name': build.deployer.first_name, 'position': build.deployer.position}
            except BaseException as e:
                pass
        return job

    def get_hosts(self, instance):
        """
        获取前端/非k8s部署后端的主机
        """
        try:
            appinfo_obj = AppInfo.objects.get(id=instance.appinfo_id)
            if appinfo_obj.app.is_k8s != 'k8s':
                return appinfo_obj.hosts
            return []
        except BaseException as e:
            return []

    def get_kubernetes(self, instance):
        try:
            appinfo_obj = AppInfo.objects.get(id=instance.appinfo_id)
            if appinfo_obj.app.category.split('.')[-1] == 'server':
                return [{'id': i.id, 'name': i.name} for i in appinfo_obj.kubernetes.all()]
            else:
                return [{'id': 0, 'name': 'DEVOPS'}]
        except BaseException as e:
            return [{'id': 0, 'name': None}]

    def get_project_info(self, instance):
        try:
            project = Project.objects.get(projectid=instance.project)
            return {'id': project.id, 'projectid': project.projectid, 'name': project.name, 'alias': project.alias}
        except:
            return {}

    def get_product_info(self, instance):
        try:
            project = Project.objects.get(projectid=instance.project)
            return {'id': project.product.id, 'name': project.product.name, 'alias': project.product.alias}
        except:
            return {}

    def get_template(self, instance):
        app_info_obj = AppInfo.objects.get(
            id=instance.appinfo_id, environment__id=instance.environment)
        data = template_generate(
            app_info_obj, f'{app_info_obj.app.name}:4preview')
        if data['ecode'] != 200:
            return {}
        return data['yaml']

    def get_is_k8s(self, instance):
        app_info_obj = AppInfo.objects.get(
            id=instance.appinfo_id, environment__id=instance.environment)
        return app_info_obj.app.is_k8s

    class Meta:
        model = PublishApp
        fields = '__all__'


class PublishOrderListSerializer(ModelSerializer):
    can_edit = serializers.SerializerMethodField()
    creator_info = serializers.SerializerMethodField()
    design_form = serializers.SerializerMethodField()

    @staticmethod
    def get_permission_from_role(user):
        # 获取当前用户分配的权限
        try:
            perms = user.roles.values(
                'permissions__method',
            ).distinct()
            return [p['permissions__method'] for p in perms]
        except AttributeError:
            return []

    def get_design_form(self, instance):
        wf = WorkflowNodeHistory.objects.filter(
            workflow__wid=instance.order_id, node=instance.node_name).first()
        if wf:
            for node in wf.node_conf['form_models']:
                if node['type'] == 'deploy':
                    # 移除发版应用
                    wf.node_conf['form_models'].remove(node)
            return {'form': wf.form, 'design': wf.node_conf}
        return {'form': {}, 'design': []}

    def get_can_edit(self, instance):
        return True

    def get_creator_info(self, instance):
        if instance.creator:
            return {'id': instance.creator.id, 'first_name': instance.creator.first_name,
                    'username': instance.creator.username}
        return {'id': '', 'first_name': '', 'username': ''}

    def get_user_obj(self):
        user = None
        request = self.context.get("request")
        if request and hasattr(request, "user"):
            user = request.user
        return user

    class Meta:
        model = PublishOrder
        exclude = ('app',)


class PublishOrderDetailSerializer(PublishOrderListSerializer):
    apps = PublishAppSerializer(many=True)
    deploy_perms = serializers.SerializerMethodField()

    def get_deploy_perms(self, instance):
        return True


class PublishOrderSerializer(ModelSerializer):
    class Meta:
        model = PublishOrder
        fields = '__all__'
        read_only_fields = ('order_id', 'creator', 'team_members',
                            'apps', 'executor', 'result', 'deploy_time')

    @staticmethod
    def check_team_members(appinfo_obj):
        team_members = [appinfo_obj.app.creator.id, appinfo_obj.app.project.manager, appinfo_obj.app.project.developer,
                        appinfo_obj.app.project.tester]
        return [i for i in set(team_members) if i]

    @transaction.atomic
    def create(self, validated_data):
        st = shortuuid.ShortUUID()
        st.set_alphabet(f"0123456789")
        order_id = f'{datetime.datetime.now().strftime("%Y%m%d%H%M%S")}{st.random(length=4)}'
        app = validated_data.get('app')
        apps = AppInfo.objects.filter(id__in=[i['id'] for i in app])
        # 团队成员
        _team_members = []
        # 创建待发布应用
        publish_apps = []
        for i in apps:
            for j in app:
                if j['id'] == i.id:
                    model = PublishApp()
                    setattr(model, 'order_id', order_id)
                    setattr(model, 'appid', i.app.appid)
                    setattr(model, 'appinfo_id', i.id)
                    setattr(model, 'name', i.app.name)
                    setattr(model, 'alias', i.app.alias)
                    setattr(model, 'project', i.app.project.projectid)
                    setattr(model, 'product', i.app.project.product.name)
                    setattr(model, 'category', i.app.category)
                    setattr(model, 'environment', i.environment.id)
                    setattr(model, 'branch', j.get('branch', i.branch))
                    setattr(model, 'image', j['image']['image'])
                    setattr(model, 'commits', j['image']['commits'])
                    setattr(model, 'apollo', j['apollo'])
                    setattr(model, 'modules', j['moduleObj'].split(
                        ':')[-1] if j.get('moduleOjb', None) else None)
                    setattr(model, 'deploy_type', 'update')
                    publish_apps.append(model)
                    _team_members.extend(self.check_team_members(i))
        PublishApp.objects.bulk_create(publish_apps)
        publish_apps = PublishApp.objects.filter(order_id=order_id)
        instance = PublishOrder.objects.create(order_id=order_id, team_members=[i for i in set(_team_members) if i],
                                               **validated_data)
        # 关联待发布应用
        instance.apps.set(publish_apps)
        return instance


class PublishAppEsListSerializer(EsSerializer, PublishAppSerializer):
    """
    ElasticSearch索引文档序列化
    """

    class Meta:
        model = PublishApp
        fields = '__all__'
