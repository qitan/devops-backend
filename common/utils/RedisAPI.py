#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
@Author  : Charles Lai
@Contact : qqing_lai@hotmail.com
@Time    : 2020/5/13 下午5:40
@FileName: RedisAPI.py
@Blog    : https://blog.imaojia.com
"""

import redis
from django_redis.client import DefaultClient
from rediscluster import ClusterConnectionPool, RedisCluster

from config import REDIS_CONFIG, CACHE_CONFIG, REDIS_CLUSTER_CONFIG


class CustomRedisCluster(DefaultClient):

    def connect(self, index):
        pool = ClusterConnectionPool(startup_nodes=CACHE_CONFIG['startup_nodes'],
                                     password=CACHE_CONFIG.get('password', ''),
                                     nodemanager_follow_cluster=True,
                                     skip_full_coverage_check=True,
                                     # decode_responses=True,
                                     )
        return RedisCluster(connection_pool=pool,
                            nodemanager_follow_cluster=True)


class RedisManage(object):

    @classmethod
    def conn(cls):
        if REDIS_CLUSTER_CONFIG.get('startup_nodes', None):
            pool = ClusterConnectionPool(startup_nodes=REDIS_CLUSTER_CONFIG['startup_nodes'],
                                         password=REDIS_CLUSTER_CONFIG.get(
                                             'password', ''),
                                         nodemanager_follow_cluster=True,
                                         decode_responses=True, )
            return RedisCluster(connection_pool=pool, nodemanager_follow_cluster=True)
        pool = redis.ConnectionPool(host=REDIS_CONFIG['host'], port=REDIS_CONFIG['port'], db=REDIS_CONFIG['db'],
                                    password=REDIS_CONFIG.get('password', ''), decode_responses=True)
        return redis.Redis(connection_pool=pool)

    @staticmethod
    def get_pubsub():
        r = redis.StrictRedis(host=REDIS_CONFIG['host'], port=REDIS_CONFIG['port'], db=REDIS_CONFIG['db'],
                              password=REDIS_CONFIG.get('password', ''))
        return r.pubsub(ignore_subscribe_messages=True)
