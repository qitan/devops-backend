#!/usr/bin/env python
# -*- encoding: utf-8 -*-
'''
@author  :   Charles Lai
@file    :   tasks_hook.py
@time    :   2023/03/09 11:38
@contact :   qqing_lai@hotmail.com
@company :   IMAOJIA Co,Ltd
'''

# here put the import lib

def print_result(task):
    print('回调结果', task.result)
