#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
@Author : Charles Lai
@Contact : qqing_lai@hotmail.com
@Time : 2020/9/15 下午5:04
@FileName: serializers.py
@Blog ：https://imaojia.com
"""

from rest_framework import serializers
from rest_framework.utils import model_meta

from dbapp.models import Menu, Permission, Role, Organization, UserProfile, AuditLog, SystemConfig, DataDict

from common.recursive import RecursiveField
from common.extends.serializers import ModelSerializer

import json


class DataDictSerializers(serializers.ModelSerializer):
    children = RecursiveField(
        read_only=True, required=False, allow_null=True, many=True)

    class Meta:
        model = DataDict
        fields = '__all__'

    def create(self, validated_data):
        validated_data['key'] = validated_data['key'].replace('.', '-')
        if validated_data['parent']:
            validated_data['key'] = f"{validated_data['parent'].key.lower()}.{validated_data['key']}"
        instance = DataDict.objects.create(**validated_data)
        return instance


class AuditLogSerializers(ModelSerializer):
    class Meta:
        model = AuditLog
        fields = '__all__'


class AuditLogActivitySerializers(ModelSerializer):
    class Meta:
        model = AuditLog
        fields = ('id', 'created_time', 'type',
                  'action', 'action_ip', 'content')


class MenuListSerializers(ModelSerializer):
    children = RecursiveField(
        read_only=True, required=False, allow_null=True, many=True)
    meta = serializers.SerializerMethodField()

    def get_meta(self, instance):
        return {'title': instance.title, 'icon': instance.icon, 'activeMenu': instance.activeMenu,
                'affix': instance.affix, 'single': instance.single}

    class Meta:
        model = Menu
        fields = '__all__'


class MenuSerializers(ModelSerializer):
    class Meta:
        model = Menu
        fields = '__all__'

    def valid_data(self, data):
        if data.get('component', None) is None or data.get('component') == 'Layout' and not data['path'].startswith(
                '/'):
            data['path'] = '/' + data['path']
        if data.get('component') and data.get('component') != 'Layout' and not data.get('is_frame'):
            data['path'] = data['path'].lstrip('/')
            data['component'] = data['component'].lstrip('/')
        if data.get('is_frame') and not data.get('path').startswith('/'):
            data['path'] = '/' + data['path']
            data['component'] = data['component'].lstrip('/')
        if data.get('redirect', None) and not data['redirect'].startswith('/'):
            data['redirect'] = '/' + data['redirect']
        return data

    def create(self, validated_data):
        validated_data = self.valid_data(validated_data)
        instance = Menu.objects.create(**validated_data)
        return instance

    def update(self, instance, validated_data):
        validated_data = self.valid_data(validated_data)
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


class UserMenuSerializers(ModelSerializer):
    meta = serializers.SerializerMethodField()

    def get_meta(self, instance):
        return {'title': instance.title, 'icon': instance.icon, 'activeMenu': instance.activeMenu,
                'affix': instance.affix, 'single': instance.single}

    class Meta:
        model = Menu
        fields = '__all__'


class PermissionListSerializers(ModelSerializer):
    children = RecursiveField(
        read_only=True, required=False, allow_null=True, many=True)

    class Meta:
        model = Permission
        fields = '__all__'


class PermissionSerializers(ModelSerializer):
    class Meta:
        model = Permission
        fields = '__all__'


class RoleListSerializers(ModelSerializer):
    menus = MenuListSerializers(many=True)
    permissions = PermissionSerializers(many=True)

    class Meta:
        model = Role
        fields = ['id', 'name', 'desc', 'menus', 'permissions']


class RoleSerializers(ModelSerializer):
    role_menus = serializers.SerializerMethodField()

    def get_role_menus(self, instance):
        qs = instance.menus.filter(parent__isnull=True)
        serializer = MenuListSerializers(instance=qs, many=True)
        return serializer.data

    class Meta:
        model = Role
        fields = '__all__'

    def create(self, validated_data):
        menus = validated_data.pop('menus')
        permissions = validated_data.pop('permissions')
        instance = Role.objects.create(**validated_data)
        instance.menus.set(menus)
        instance.permissions.set(permissions)
        return instance


class OrganizationSerializers(ModelSerializer):
    children = RecursiveField(
        read_only=True, required=False, allow_null=True, many=True)

    class Meta:
        model = Organization
        fields = '__all__'


class UserProfileListSerializers(ModelSerializer):
    user_department = serializers.SerializerMethodField()
    user_director = serializers.SerializerMethodField()

    def get_user_department(self, instance):
        return [{'org_id': i.id, 'org_name': i.name} for i in instance.department.all()]

    def get_user_director(self, instance):
        leader_ou = [i.leader_user_id for i in instance.department.all()]
        leaders = UserProfile.objects.filter(feishu_openid__in=leader_ou)
        return [[{'id': i.id, 'name': i.name} for i in leaders]]

    class Meta:
        model = UserProfile
        exclude = ('password', 'dn')


class UserProfileDetailSerializers(ModelSerializer):
    user_roles = serializers.SerializerMethodField()
    routers = serializers.SerializerMethodField()
    permissions = serializers.SerializerMethodField()
    user_department = serializers.SerializerMethodField()
    user_director = serializers.SerializerMethodField()

    def get_user_director(self, instance):
        leader_ou = [i.leader_user_id for i in instance.department.all()]
        leaders = UserProfile.objects.filter(feishu_openid__in=leader_ou)
        return [[{'id': i.id, 'name': i.name} for i in leaders]]

    def get_user_department(self, instance):
        return [{'org_id': i.id, 'org_name': i.name} for i in instance.department.all()]

    def get_user_roles(self, instance):
        try:
            qs = instance.roles.all()
            return [{'id': i.id, 'name': i.name, 'desc': i.desc} for i in qs]
        except BaseException as e:
            return []

    def get_permissions(self, instance):
        perms = instance.roles.values(
            'permissions__method',
        ).distinct()
        if instance.is_superuser:
            return ['admin']
        return [p['permissions__method'] for p in perms if p['permissions__method']]

    def get_routers(self, instance):
        qs = []
        if instance.is_superuser or 'admin' in [p['permissions__method'] for p in
                                                instance.roles.values('permissions__method')]:
            qs = Menu.objects.filter(parent__isnull=True)
            serializer = MenuListSerializers(instance=qs, many=True)
            tree_data = serializer.data
        else:
            [qs.extend(i.menus.all()) for i in instance.roles.all()]
            serializer = UserMenuSerializers(instance=qs, many=True)

            # 组织用户拥有的菜单列表
            tree_dict = {}
            tree_data = []
            try:
                for item in serializer.data:
                    tree_dict[item['id']] = item
                for i in tree_dict:
                    if tree_dict[i]['parent']:
                        pid = tree_dict[i]['parent']
                        parent = tree_dict[pid]
                        parent.setdefault('children', []).append(tree_dict[i])
                    else:
                        tree_data.append(tree_dict[i])
            except:
                tree_data = serializer.data
        return tree_data

    class Meta:
        model = UserProfile
        exclude = ('avatar',)


class UserProfileSerializers(ModelSerializer):

    class Meta:
        model = UserProfile
        exclude = ('avatar',)

    def create(self, validated_data):
        roles = validated_data.pop('roles')
        departments = validated_data.pop('department')
        instance = UserProfile.objects.create(**validated_data)
        instance.set_password(validated_data['password'])
        instance.save()
        instance.department.set(departments)
        instance.roles.set(roles)
        return instance


class SystemConfigListSerializers(ModelSerializer):
    config = serializers.SerializerMethodField()

    def get_config(self, instance):
        config = json.loads(instance.config)
        try:
            config['password'] = ''
            config['token'] = ''
        except BaseException as e:
            pass
        return config

    class Meta:
        model = SystemConfig
        fields = '__all__'


class SystemConfigSerializers(ModelSerializer):
    class Meta:
        model = SystemConfig
        fields = '__all__'
