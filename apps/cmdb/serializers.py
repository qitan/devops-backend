#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
@Author : Charles Lai
@Contact : qqing_lai@hotmail.com
@Time : 2020/9/15 下午7:46
@FileName: serializers.py
@Blog ：https://imaojia.com
"""

import re
from django.apps import apps
from django.db.models import Q
from rest_framework.relations import Hyperlink, PKOnlyObject
from rest_framework.fields import (  # NOQA # isort:skip
    CreateOnlyDefault, CurrentUserDefault, SkipField, empty
)

from elasticsearch_dsl import Document
from elasticsearch_dsl.response import Hit

from cmdb.serializer import *

import pytz
import datetime
import logging

logger = logging.getLogger('cmdb_es')


class FileUploadSerializers(serializers.ModelSerializer):
    class Meta:
        model = FileUpload
        fields = '__all__'
        read_only_fields = ('uploader',)
