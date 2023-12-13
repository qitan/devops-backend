#!/usr/bin/env python
# -*- encoding: utf-8 -*-
'''
@Author  :    Charles Lai
@Contact :    qqing_lai@hotmail.com
@Time    :    2021/12/27 12:44
@FileName:    storage.py
@Blog    :    https://imaojia.com
'''

from typing import Optional
from django.core.files.storage import FileSystemStorage, Storage, DefaultStorage
from django.utils._os import safe_join


class FileUploadStorage(FileSystemStorage):
    """
    上传存储类
    """

    def __init__(self, location=None, base_url=None, file_permissions_mode=None,
                 directory_permissions_mode=None, upload_root=None):
        self.upload_root = upload_root
        super().__init__(location=location, base_url=base_url, file_permissions_mode=file_permissions_mode,
                         directory_permissions_mode=directory_permissions_mode)

    def path(self, name: str) -> str:
        if self.upload_root:
            return safe_join(self.upload_root, name)
        return safe_join(self.location, name)
