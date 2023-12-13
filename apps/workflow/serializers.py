"""
@Author : Ken Chen
@Contact : 316084217@qq.com
@Time : 2021/11/2 上午9:50
"""

from rest_framework import serializers
from dbapp.models import Product, Project

from common.recursive import RecursiveField
from dbapp.models import UserProfile
from dbapp.models import WorkflowCategory, Workflow, WorkflowNodeHistory, WorkflowTemplate, \
    WorkflowTemplateRevisionHistory, WorkflowNodeHistoryCallback
from common.extends.serializers import ModelSerializer
from django.conf import settings
import logging

logger = logging.getLogger(__name__)


class WorkflowTemplateSerializer(ModelSerializer):
    projects_info = serializers.SerializerMethodField()
    env_info = serializers.SerializerMethodField()

    def get_env_info(self, instance):
        if instance.environment:
            return {'name': instance.environment.name, 'alias': instance.environment.alias}
        return {}

    def get_projects_info(self, instance):
        data = []
        product_ids = {}
        for i in instance.projects:
            if i[0] not in product_ids:
                product_ids[i[0]] = []
            product_ids[i[0]].append(i[1])
        for k, v in product_ids.items():
            product = Product.objects.get(id=k)
            _projects = Project.objects.filter(id__in=v)
            data.append({'value': product.id, 'name': product.name, 'label': product.alias,
                         'children': [{'value': i.id, 'name': i.name, 'label': i.alias} for i in _projects]})
        return data

    class Meta:
        model = WorkflowTemplate
        fields = '__all__'


class WorkflowTemplateForRetrieveSerializer(ModelSerializer):

    class Meta:
        model = WorkflowTemplate
        fields = '__all__'


class WorkflowRevisionTemplateSerializer(ModelSerializer):
    class Meta:
        model = WorkflowTemplateRevisionHistory
        fields = '__all__'


class WorkflowCategorySerializer(ModelSerializer):
    workflows = serializers.SerializerMethodField()

    def get_workflows(self, instance):
        qs = instance.workflowtemplate_set.filter(enabled=True)
        return [{'id': i.id, 'name': i.name, 'comment': i.comment} for i in qs]

    class Meta:
        model = WorkflowCategory
        fields = ['id', 'name', 'desc', 'sort', 'workflows']


class WorkflowNodeHistorySerializer(ModelSerializer):
    class Meta:
        model = WorkflowNodeHistory
        fields = '__all__'
        read_only_fields = ('created_time',)


class WorkflowNodeHistoryOperatorSerializers(ModelSerializer):
    class Meta:
        model = UserProfile
        fields = ['id', 'username', 'first_name']


class WorkflowNodeHistoryListSerializer(WorkflowNodeHistorySerializer):
    operator = WorkflowNodeHistoryOperatorSerializers()
    created_time = serializers.DateTimeField(format=settings.DATETIME_FORMAT)
    callback_status = serializers.SerializerMethodField()

    def get_callback_status(self, instance):
        callback_objs = WorkflowNodeHistoryCallback.objects.filter(
            node_history=instance)
        if not callback_objs:
            return None
        return callback_objs.first().get_status_display()


class WorkflowListSerializer(ModelSerializer):
    template = serializers.SerializerMethodField()
    template_id = serializers.SerializerMethodField()
    creator = serializers.SerializerMethodField()
    created_time = serializers.DateTimeField(format=settings.DATETIME_FORMAT)
    update_time = serializers.DateTimeField(format=settings.DATETIME_FORMAT)
    current_node_handler = serializers.SerializerMethodField()
    category = serializers.SerializerMethodField()

    def get_template(self, instance):
        return instance.template.__str__()

    def get_template_id(self, instance):
        return instance.template.id

    def get_current_node_handler(self, instance):
        if instance.status == '已完成':
            wnode = WorkflowNodeHistory.objects.filter(workflow=instance.id,
                                                       node=instance.node).first()
            if wnode:
                return wnode.operator.__str__()
            return ''

        node_conf = instance.template.get_node_conf(instance.node)
        members = node_conf.get('members')
        members_str = ''
        for member in members:
            name = member.split('@')[-1]
            members_str += f'{name} '
        return members_str

    def get_creator(self, instance):
        return instance.creator.__str__()

    def get_category(self, instance):
        return instance.template.category.name

    class Meta:
        model = Workflow
        fields = '__all__'
        read_only_fields = ('created_time', 'update_time')


class WorkflowRetrieveSerializer(WorkflowListSerializer):
    template = WorkflowTemplateSerializer()
    creator_department = serializers.SerializerMethodField()

    def get_creator_department(self, instance):
        dep = instance.creator.department.all().first()
        return dep and dep.__str__()


class WorkflowSerializer(ModelSerializer):
    template = serializers.PrimaryKeyRelatedField(
        queryset=WorkflowTemplateRevisionHistory.objects)

    class Meta:
        model = Workflow
        fields = '__all__'
        read_only_fields = ('created_time', 'update_time')


class WorkflowNodeHistoryCallbackSerializer(ModelSerializer):
    trigger = WorkflowNodeHistoryOperatorSerializers()

    class Meta:
        model = WorkflowNodeHistoryCallback
        fields = '__all__'
