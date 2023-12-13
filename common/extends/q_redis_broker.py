#!/usr/bin/env python
# -*- encoding: utf-8 -*-
'''
@author  :   Charles Lai
@file    :   q_redis_broker.py
@time    :   2023/09/11 11:15
@contact :   qqing_lai@hotmail.com
'''

# here put the import lib
from django_q.brokers.redis_broker import Redis as BaseRedis
from django_q.conf import Conf


# bug: site-packages/django_q/brokers/redis_broker.py", line 44, in info
#     self._info = f"Redis {info['redis_version']}"
# KeyError: 'redis_version'


class Redis(BaseRedis):
    def __init__(self, list_key: str = Conf.PREFIX):
        super().__init__(list_key)

    def info(self) -> str:
        if not self._info:
            info = self.connection.info("server")
            try:
                # 尝试获取版本号
                self._info = f"Redis {info['redis_version']}"
            except BaseException as e:
                self._info = list(info.values())[0].get('redis_version', 'unknown')
        return self._info
