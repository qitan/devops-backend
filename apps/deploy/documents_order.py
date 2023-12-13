#!/usr/bin/env python
# -*- encoding: utf-8 -*-
'''
@author  :   Charles Lai
@file    :   documents_order.py
@time    :   2023/04/21 15:06
@contact :   qqing_lai@hotmail.com
'''

# here put the import lib
from dbapp.model.model_deploy import PublishApp

from common.utils.ElasticSearchAPI import CustomDocument, Text, Date, Keyword, Integer, EsNested, Object
from common.utils.DocumentRegistry import registry

from config import CMDB_SOURCE_INDEX, ELASTICSEARCH_PREFIX

from deploy.serializers_order import PublishAppEsListSerializer

import datetime


@registry.register_document
class PublishAppDocument(CustomDocument):
    """
    工单应用索引文档 - 按年创建索引
    """
    project_info = Object()
    product_info = Object()
    region_info = Object()

    class Index:
        name = ELASTICSEARCH_PREFIX + 'publishapp-*'
        aliases = {ELASTICSEARCH_PREFIX + 'publishapp': {}}

    class Django:
        model = PublishApp
        serializer = PublishAppEsListSerializer
        fields = '__all__'

    def save(self, **kwargs):
        kwargs['index'] = f"{ELASTICSEARCH_PREFIX}publishapp-{datetime.datetime.now().strftime('%Y')}"
        return super().save(**kwargs)
