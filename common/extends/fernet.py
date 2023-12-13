#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
@Author : Charles Lai
@Contact : qqing_lai@hotmail.com
@Time : 2021/1/14 下午7:34
@FileName: fernet.py
@Blog ：https://imaojia.com
"""

from fernet_fields import EncryptedField
from django.db.models import JSONField


class EncryptedJsonField(EncryptedField, JSONField):
    pass
