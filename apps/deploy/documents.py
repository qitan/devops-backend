#!/usr/bin/env python
# -*- encoding: utf-8 -*-
'''
@author  :   Charles Lai
@file    :   documents.py
@time    :   2023/04/20 17:39
@contact :   qqing_lai@hotmail.com
'''

# here put the import lib
from common.variables import my_normalizer, CI_RESULT_INDEX, CD_RESULT_INDEX
from dbapp.model.model_deploy import BuildJob, DeployJob

from common.utils.ElasticSearchAPI import CustomDocument, Text, Date, Keyword, Integer, EsNested, Object
from common.utils.DocumentRegistry import registry

from config import CMDB_SOURCE_INDEX, ELASTICSEARCH_PREFIX

import datetime

from deploy.serializers import BuildJobEsListSerializer, \
    DeployJobEsListSerializer


class BuildJobResultDocument(CustomDocument):
    """
    构建结果 - 按月创建索引
    """
    id = Integer()
    result = Text()
    console_output = Text()
    created_at = Date()
    status = Integer()

    class Index:
        name = ELASTICSEARCH_PREFIX + f'{CI_RESULT_INDEX}-*'
        aliases = {ELASTICSEARCH_PREFIX + CI_RESULT_INDEX: {}}

    def save(self, **kwargs):
        self.created_at = datetime.datetime.now()
        kwargs[
            'index'] = f"{ELASTICSEARCH_PREFIX}{CI_RESULT_INDEX}-{self.created_at.strftime('%Y%m')}"
        return super().save(**kwargs)


class DeployJobResultDocument(CustomDocument):
    """
    发布结果 - 按月创建索引
    """
    id = Integer()
    result = Text()
    created_at = Date()
    status = Integer()

    class Index:
        name = ELASTICSEARCH_PREFIX + f'{CD_RESULT_INDEX}-*'
        aliases = {ELASTICSEARCH_PREFIX + CD_RESULT_INDEX: {}}

    def save(self, **kwargs):
        self.created_at = datetime.datetime.now()
        kwargs[
            'index'] = f"{ELASTICSEARCH_PREFIX}{CD_RESULT_INDEX}-{self.created_at.strftime('%Y%m')}"
        return super().save(**kwargs)


@registry.register_document
class BuildJobDocument(CustomDocument):
    """
    持续构建索引文档 - 按年创建索引
    """
    deployer_info = Object()  # 构建人信息
    appinfo_obj_info = Object()  # 应用信息
    project_info = Object()
    region_info = Object()
    environment_info = Object()

    class Index:
        name = ELASTICSEARCH_PREFIX + 'buildjob-*'
        aliases = {ELASTICSEARCH_PREFIX + 'buildjob': {}}

    class Django:
        model = BuildJob
        serializer = BuildJobEsListSerializer
        fields = '__all__'

    def save(self, **kwargs):
        kwargs['index'] = f"{ELASTICSEARCH_PREFIX}buildjob-{datetime.datetime.now().strftime('%Y')}"
        return super().save(**kwargs)


@registry.register_document
class DeployJobDocument(CustomDocument):
    """
    持续部署索引文档 - 按年创建索引
    """
    deployer_info = Object(
    )
    appinfo_obj_info = Object()  # 应用信息
    project_info = Object()
    region_info = Object()
    environment_info = Object()

    class Index:
        name = ELASTICSEARCH_PREFIX + "deployjob-*"
        aliases = {ELASTICSEARCH_PREFIX + 'deployjob': {}}

    class Django:
        model = DeployJob
        serializer = DeployJobEsListSerializer
        fields_remap = {'kubernetes': Text(), 'result': Text()}  # 定义需要重新映射的字段
        fields = '__all__'

    def save(self, **kwargs):
        kwargs['index'] = f"{ELASTICSEARCH_PREFIX}deployjob-{datetime.datetime.now().strftime('%Y')}"
        return super().save(**kwargs)
