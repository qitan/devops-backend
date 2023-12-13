#!/usr/bin/env python
# -*- encoding: utf-8 -*-
'''
@author  :   Charles Lai
@file    :   ext_func.py
@time    :   2023/05/22 15:14
@contact :   qqing_lai@hotmail.com
'''

# here put the import lib
import logging
from dbapp.models import MicroApp
from dbapp.models import UserProfile

from dbapp.models import Workflow, WorkflowTemplate, WorkflowTemplateRevisionHistory
from workflow.notice import get_member_user_ids
from workflow.serializers import WorkflowNodeHistorySerializer, WorkflowSerializer

logger = logging.getLogger('drf')


def members_handle(data, field, leader: UserProfile, owner: UserProfile = None):
    data[field] = list(set(data[field]))
    return data


def create_workflow(form, workflow_data, workflow_template, user):
    template_id = workflow_template['id']
    template_obj = WorkflowTemplate.objects.get(pk=template_id)
    template_obj.pk = None
    template_obj.__class__ = WorkflowTemplateRevisionHistory

    # 处理发版工单
    leader = None
    for _, v in form.items():
        if isinstance(v, (dict,)) and v.get('applist', None):
            try:
                # 申请应用
                filter = {'appid': v['applist'][0]}
                if isinstance(v['applist'][0], (dict, )):
                    # 发布应用
                    filter = {'id': v['applist'][0]['app']['id']}
                microapp_obj = MicroApp.objects.get(**filter)
                leader = UserProfile.objects.get(
                    id=microapp_obj.project.manager)
            except BaseException as e:
                logger.info(f'处理项目信息异常==={e}')

    for (index, i) in enumerate(template_obj.nodes):
        if index > 0:
            # 合并前端传递的处理人员
            # 排除发起节点
            extra_member = workflow_template['nodes'][index]['members']
            i['members'].extend(extra_member)
            i['members'] = list(set(i['members']))
        if i['pass_type'] == 'passed':
            # 节点无需审批，添加发起人为处理人
            i['members'].append(
                f'user@{user.id}@{user.first_name}')
    template_obj.save()
    template_nodes = template_obj.nodes
    if len(template_nodes) == 0:
        return False, f'工单模板 {template_obj.name} 没有配置节点'

    first_template_node = template_nodes[0]
    members = first_template_node.get('members', [])
    if members:
        user_ids = get_member_user_ids(members)
        if not user.is_superuser and str(user.id) not in user_ids:
            return False, f'发起工单失败，当前工单只允许指定人员发起'
    _flag = workflow_data.pop('flag', 'normal')
    deploy_method = workflow_data.pop('deploy_method', None)
    workflow_data['extra'] = {'deploy_method': deploy_method}
    workflow_data['workflow_flag'] = _flag
    workflow_data['template'] = template_obj.pk
    workflow_data['node'] = first_template_node['name']
    workflow_data['creator'] = user.id
    workflow_data['status'] = Workflow.STATUS.wait
    serializer = WorkflowSerializer(data=workflow_data)
    if not serializer.is_valid():
        return False, serializer.errors
    workflow_obj = serializer.save()
    # 生成工单号
    workflow_obj.generate_wid(save=True)

    # 判断发起节点中， 有没有表单类型是 节点处理人的
    first_node_form_models = first_template_node.get('form_models', [])
    for field in first_node_form_models:
        if field['type'] != 'nodeHandler':
            continue
        # 如果是节点处理人类型的， 根据 配置的节点， 将选中的人员， 改到对应的节点绑定人员中
        type_ext_conf = field['type_ext_conf']
        node_handler_id = type_ext_conf['node_handler_id']
        for node in template_nodes:
            if node['id'] != node_handler_id:
                continue
            selected_user_list = form[field['name']]
            if isinstance(selected_user_list, str):
                selected_user_list = [selected_user_list]
            mapping_to_node_members_list = []
            for u in selected_user_list:
                username, _ = u.split('@')
                selected_user_obj = UserProfile.objects.get(
                    username=username)
                mapping_to_node_members_list.append(
                    f'user@{selected_user_obj.id}@{selected_user_obj.first_name}')
            # 此处将完全覆盖原来的绑定人员配置
            node['members'] = mapping_to_node_members_list

    template_obj.save()

    node_form = {
        'workflow': workflow_obj.pk,
        'node': workflow_obj.node,
        'form': form,
        'operator': user.id
    }
    node_serializer = WorkflowNodeHistorySerializer(data=node_form)
    if not node_serializer.is_valid():
        return False, node_serializer.errors
    node_obj = node_serializer.save()
    return True, {'data': serializer.data, 'workflow_obj': workflow_obj, 'node_obj': node_obj}
