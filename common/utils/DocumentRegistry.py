#!/usr/bin/env python
# -*- encoding: utf-8 -*-
'''
@author  :   Charles Lai
@file    :   DocumentRegistry.py
@time    :   2023/04/20 17:39
@contact :   qqing_lai@hotmail.com
'''

# here put the import lib
from django.core.exceptions import ImproperlyConfigured
from elasticsearch_dsl import AttrDict

from collections import defaultdict

from common.variables import ES_MODEL_FIELD_MAP


class DocumentRegistry(object):
    """
    Registry of models classes to a set of Document classes.
    """

    def __init__(self):
        self._models = defaultdict(set)

    def register_document(self, document):
        django_meta = getattr(document, 'Django')
        # Raise error if Django class can not be found
        if not django_meta:
            message = "You must declare the Django class inside {}".format(
                document.__name__)
            raise ImproperlyConfigured(message)

        # Keep all django related attribute in a django_attr AttrDict
        data = {'model': getattr(document.Django, 'model')}
        django_attr = AttrDict(data)

        if not django_attr.model:
            raise ImproperlyConfigured("You must specify the django model")

        # Add The model fields into elasticsearch mapping field
        model_field_names = getattr(document.Django, "fields", [])
        model_field_exclude = getattr(document.Django, "exclude", [])
        if model_field_names == '__all__':
            model_field_names = [
                i.name for i in django_attr['model']._meta.fields if i.name not in model_field_exclude]
        model_field_remap = getattr(document.Django, "fields_remap", {})
        for field_name in model_field_names:
            django_field = django_attr.model._meta.get_field(field_name)
            field_instance = ES_MODEL_FIELD_MAP[django_field.__class__]
            if field_name in model_field_remap:
                field_instance = model_field_remap[field_name]
            document._doc_type.mapping.field(field_name, field_instance)
        try:
            if not document._index.exists():
                document.init()
        except:
            pass
        return document


registry = DocumentRegistry()
