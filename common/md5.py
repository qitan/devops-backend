#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
@Author : Charles Lai
@Contact : qqing_lai@hotmail.com
@Time : 2020/11/27 下午2:39
@FileName: md5.py
@Blog ：https://imaojia.com
"""

from functools import partial
import hashlib


def md5(data, block_size=65536):
    # 创建md5对象
    m = hashlib.md5()
    # 对django中的文件对象进行迭代
    for item in iter(partial(data.read, block_size), b''):
        # 把迭代后的bytes加入到md5对象中
        m.update(item)

    return m.hexdigest()
