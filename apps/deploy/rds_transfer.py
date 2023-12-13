#!/usr/bin/env python
# -*- encoding: utf-8 -*-
'''
@author  :   Charles Lai
@file    :   rds_transfer.py
@time    :   2023/05/10 16:29
@contact :   qqing_lai@hotmail.com
'''

# here put the import lib
def rds_transfer_es(document, instance):
    document_serializer = getattr(document.Django, "serializer", None)
    if document_serializer:
        serializer = document_serializer(instance)
        data = serializer.data
    else:
        data = instance.__dict__
    model_field_exclude = getattr(document.Django, "exclude", [])
    model_field_names = getattr(document.Django, "fields", [])
    if model_field_names == '__all__':
        data.pop('_state', None)
    else:
        _data = {}
        for field in model_field_names:
            _data[field] = getattr(instance, field, None)
        data = _data
    for i in model_field_exclude:
        data.pop(i, None)
    data['_id'] = data['id']
    docu = document(**data)
    docu.save(skip_empty=False)
