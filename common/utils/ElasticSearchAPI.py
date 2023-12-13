#!/usr/bin/env python
# -*- encoding: utf-8 -*-
'''
@Author  :    Charles Lai
@Contact :    qqing_lai@hotmail.com
@Time    :    2021/10/26 14:26
@FileName:    ElasticSearchAPI.py
@Blog    :    https://imaojia.com
'''

from elasticsearch_dsl.serializer import serializer
from datetime import datetime
from elasticsearch_dsl import Document, Date, Integer, Keyword, Text, connections

from common.variables import ES_FIELD_MAP, ES_TYPE_MAP, my_normalizer, ES_MODEL_FIELD_MAP
from elasticsearch_dsl import Object, Nested as EsNested

from elasticsearch.exceptions import NotFoundError

from elasticsearch.helpers import bulk
from elasticsearch import Elasticsearch
from elasticsearch.client import IndicesClient
from datetime import datetime
from elasticsearch_dsl import Search as BaseSearch, Index as BaseIndex, Document, Date, Integer, Keyword, Text, \
    connections
from elasticsearch_dsl import analyzer, tokenizer
from six import iteritems, string_types


from config import ELASTICSEARCH, ELASTICSEARCH_PREFIX


class Mapping:

    @staticmethod
    def _generate_mapping(table):
        mapping = {}
        for field in table.fields.all():
            if field.is_multi:
                mapping[field.name] = Keyword(multi=True)
            else:
                mapping[field.name] = ES_FIELD_MAP[field.type]
            if field.is_related:
                # 外键关联, 额外添加field_data字段
                mapping[f"{field.name}_data"] = EsNested()
        return mapping

    def generate_data_mapping(self, table):
        system_mapping = {
            "S-creator": ES_FIELD_MAP[0],
            "S-creation-time": ES_FIELD_MAP[6],
            "S-modified-time": ES_FIELD_MAP[6],
            "S-last-modified": ES_FIELD_MAP[0]
        }
        field_mapping = self._generate_mapping(table)
        return dict(**system_mapping, **field_mapping)

    def generate_history_data_mapping(self, table):
        system_mapping = {
            "S-data-id": ES_FIELD_MAP[0],
            "S-changer": ES_FIELD_MAP[0],
            "S-update-time": ES_FIELD_MAP[6]
        }
        field_mapping = self._generate_mapping(table)
        return dict(**system_mapping, **field_mapping)

    def generate_deleted_data_mapping(self, table):
        system_mapping = {
            "S-delete-people": ES_FIELD_MAP[0],
            "S-delete-time": ES_FIELD_MAP[6]
        }
        field_mapping = self._generate_mapping(table)
        return dict(**system_mapping, **field_mapping)


class Search(BaseSearch):
    def __init__(self, prefix=False, **kwargs):
        if kwargs.get('index', None) and prefix:
            if isinstance(kwargs['index'], string_types):
                kwargs['index'] = f"{ELASTICSEARCH_PREFIX}{kwargs['index']}"
            elif isinstance(kwargs['index'], list):
                kwargs['index'] = [
                    f"{ELASTICSEARCH_PREFIX}{i}" for i in kwargs['index']]
            elif isinstance(kwargs['index'], tuple):
                kwargs['index'] = tuple(
                    f"{ELASTICSEARCH_PREFIX}{i}" for i in kwargs['index'])
            else:
                raise Exception('索引名称格式错误!')
        super(Search, self).__init__(**kwargs)


class Index(BaseIndex):

    def __init__(self, name, using="default"):
        name = f"{ELASTICSEARCH_PREFIX}{name}"
        super(Index, self).__init__(name, using=using)

    def rebuild_index(self, using=None, **kwargs):
        """
        Creates the index in elasticsearch.

        Any additional keyword arguments will be passed to
        ``Elasticsearch.indices.create`` unchanged.
        """
        return self._get_connection(using).reindex(body=kwargs)


class CustomDocument(Document):

    @staticmethod
    def gen_data(data, index, pk=None):
        for i in data:
            i['_index'] = index
            if pk:
                i['instanceid'] = i[pk]
            i['_id'] = i[pk]
            yield i

    @classmethod
    def bulk_save(cls, data, using=None, index=None, pk=None, validate=True, skip_empty=True, return_doc_meta=False,
                  **kwargs):
        """
        批量创建

        : param data: [{'instanceid': 's3', 'inner_ip': '1.1.1.3'},{'instanceid': 's4', 'inner_ip': '1.1.1.4'}]
        """
        es = cls._get_connection(cls._get_using(using))
        data = cls.gen_data(data, cls._default_index(index), pk)
        return bulk(es, data)


def generate_docu(table, index_version=None):
    index_name = f"{table.name}-{index_version}" if index_version else table.name
    _tbindex = Index(index_name)
    _tbindex.analyzer(my_normalizer)
    _tbindex.settings(number_of_shards=3, number_of_replicas=1)
    _fields = Mapping().generate_data_mapping(table)
    docu = type(index_name, (CustomDocument,), _fields)
    return _tbindex.document(docu)


def generate_history_docu(table):
    _tbindex = Index(table.name + '_history')
    _tbindex.settings(number_of_shards=3, number_of_replicas=1)
    _fields = Mapping().generate_history_data_mapping(table)
    docu = type(table.name + '_history', (Document,), _fields)
    return _tbindex.document(docu)
