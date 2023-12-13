#!/usr/bin/env python
# -*- encoding: utf-8 -*-
'''
@Author  :    Charles Lai
@Contact :    qqing_lai@hotmail.com
@Time    :    2021/08/03 10:42
@FileName:    serializers.py
@Blog    :    https://imaojia.com
'''
from elasticsearch_dsl import Document
from elasticsearch_dsl.response import Hit
from rest_framework.serializers import Field, ModelSerializer as BaseModelSerializer, Serializer
from rest_framework.fields import SkipField
from rest_framework.relations import PKOnlyObject
from django.utils.translation import ugettext_lazy as _
from collections import OrderedDict


class ModelSerializer(BaseModelSerializer):

    def to_representation(self, instance):
        """
        Object instance -> Dict of primitive datatypes.
        """
        ret = OrderedDict()
        fields = self._readable_fields

        for field in fields:
            try:
                attribute = field.get_attribute(instance)
            except SkipField:
                continue

            # We skip `to_representation` for `None` values so that fields do
            # not have to explicitly deal with that case.
            #
            # For related fields with `use_pk_only_optimization` we need to
            # resolve the pk value.
            check_for_none = attribute.pk if isinstance(
                attribute, PKOnlyObject) else attribute
            if check_for_none is None:
                ret[field.field_name] = None
            else:
                if field.field_name == 'name':
                    try:
                        ret[field.field_name] = field.to_representation(
                            attribute).lower()
                    except:
                        ret[field.field_name] = field.to_representation(
                            attribute)
                else:
                    ret[field.field_name] = field.to_representation(attribute)
        return ret


class EsSerializer(BaseModelSerializer):
    """
    ElasticSearch索引文档序列化
    """

    def to_representation(self, instance):
        if isinstance(instance, (Document, Hit,)):
            return instance.to_dict()
        return super().to_representation(instance)


class BooleanField(Field):
    default_error_messages = {
        'invalid': _('"{input}" is not a valid boolean.')
    }
    initial = None
    TRUE_VALUES = {
        't', 'T',
        'y', 'Y', 'yes', 'YES',
        'true', 'True', 'TRUE',
        'on', 'On', 'ON',
        '1', 1,
        True
    }
    FALSE_VALUES = {
        'f', 'F',
        'n', 'N', 'no', 'NO',
        'false', 'False', 'FALSE',
        'off', 'Off', 'OFF',
        '0', 0, 0.0,
        False
    }
    NULL_VALUES = {'n', 'N', 'null', 'Null', 'NULL', '', None}

    def __init__(self, **kwargs):
        super(BooleanField, self).__init__(**kwargs)

    def to_internal_value(self, data):
        try:
            if data in self.TRUE_VALUES:
                return True
            elif data in self.FALSE_VALUES:
                return False
            elif data in self.NULL_VALUES:
                return None
        except TypeError:  # Input is an unhashable type
            pass
        self.fail('invalid', input=data)

    def to_representation(self, value):
        if value in self.NULL_VALUES:
            return None
        if value in self.TRUE_VALUES:
            return True
        elif value in self.FALSE_VALUES:
            return False
        return bool(value)


class UnusefulSerializer(Serializer):
    """无用的序列化类"""
    pass
