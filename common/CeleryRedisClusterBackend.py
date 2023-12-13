# -*- coding: utf-8 -*-
"""
    celery.backends.rediscluster
    https://github.com/hbasria/celery-redis-cluster-backend/blob/master/celery_redis_cluster_backend/redis_cluster.py
    ~~~~~~~~~~~~~~~~~~~~~
    Redis cluster result store backend.
    CELERY_REDIS_CLUSTER_BACKEND_SETTINGS = {
        startup_nodes: [{"host": "127.0.0.1", "port": "6379"}]
    }

    Usage:
        CELERY_RESULT_BACKEND = "celery_redis_cluster_backend.redis_cluster.RedisClusterBackend"
        CELERY_REDIS_CLUSTER_SETTINGS = { 'startup_nodes': [
            {"host": "localhost", "port": "6379"},
            {"host": "localhost", "port": "6380"},
            {"host": "localhost", "port": "6381"}
        ]}

    Updated: 20211109
"""
from __future__ import absolute_import

import time
from contextlib import contextmanager
from functools import partial
from ssl import CERT_NONE, CERT_OPTIONAL, CERT_REQUIRED
from celery.backends.asynchronous import AsyncBackendMixin, BaseResultConsumer

from kombu.utils import cached_property, retry_over_time

from celery import states
from celery._state import task_join_will_block
from celery.five import string_t, text_t
from celery.canvas import maybe_signature
from celery.exceptions import ChordError, ImproperlyConfigured
from celery.utils.serialization import strtobool
from celery.utils.log import get_logger
from celery.utils.time import humanize_seconds

from celery.backends.base import KeyValueStoreBackend

from rediscluster import RedisCluster

get_redis_error_classes = None  # noqa

__all__ = ['RedisClusterBackend']

REDIS_MISSING = """\
You need to install the redis-py-cluster library in order to use \
the Redis result store backend."""

E_REDIS_MISSING = """
You need to install the redis library in order to use \
the Redis result store backend.
"""

E_REDIS_SENTINEL_MISSING = """
You need to install the redis library with support of \
sentinel in order to use the Redis result store backend.
"""

W_REDIS_SSL_CERT_OPTIONAL = """
Setting ssl_cert_reqs=CERT_OPTIONAL when connecting to redis means that \
celery might not valdate the identity of the redis broker when connecting. \
This leaves you vulnerable to man in the middle attacks.
"""

W_REDIS_SSL_CERT_NONE = """
Setting ssl_cert_reqs=CERT_NONE when connecting to redis means that celery \
will not valdate the identity of the redis broker when connecting. This \
leaves you vulnerable to man in the middle attacks.
"""

E_REDIS_SSL_PARAMS_AND_SCHEME_MISMATCH = """
SSL connection parameters have been provided but the specified URL scheme \
is redis://. A Redis SSL connection URL should use the scheme rediss://.
"""

E_REDIS_SSL_CERT_REQS_MISSING_INVALID = """
A rediss:// URL must have parameter ssl_cert_reqs and this must be set to \
CERT_REQUIRED, CERT_OPTIONAL, or CERT_NONE
"""

E_LOST = 'Connection to Redis lost: Retry (%s/%s) %s.'

E_RETRY_LIMIT_EXCEEDED = """
Retry limit exceeded while trying to reconnect to the Celery redis result \
store backend. The Celery application must be restarted.
"""

logger = get_logger(__name__)
error = logger.error


class RedisClusterBackend(KeyValueStoreBackend, AsyncBackendMixin):
    """Redis task result store."""

    #: redis client module.
    redis = RedisCluster

    startup_nodes = None
    max_connections = None
    init_slot_cache = True

    supports_autoexpire = True
    supports_native_join = True
    implements_incr = True

    def __init__(self, *args, **kwargs):
        super(RedisClusterBackend, self).__init__(expires_type=int, **kwargs)
        conf = self.app.conf

        if self.redis is None:
            raise ImproperlyConfigured(REDIS_MISSING)

        # For compatibility with the old REDIS_* configuration keys.
        def _get(key):
            for prefix in 'CELERY_REDIS_{0}', 'REDIS_{0}':
                try:
                    return conf[prefix.format(key)]
                except KeyError:
                    pass

        self.conn_params = self.app.conf.get('CELERY_REDIS_CLUSTER_SETTINGS', {
            'startup_nodes': [{'host': _get('HOST') or 'localhost', 'port': _get('PORT') or 6379}]
        })
        if self.conn_params is not None:
            if not isinstance(self.conn_params, dict):
                raise ImproperlyConfigured(
                    'RedisCluster backend settings should be grouped in a dict')

        try:
            new_join = strtobool(self.conn_params.pop('new_join'))
            if new_join:
                self.apply_chord = self._new_chord_apply
                self.on_chord_part_return = self._new_chord_return

        except KeyError:
            pass

        self.expires = self.prepare_expires(None, type=int)
        self.connection_errors, self.channel_errors = (
            get_redis_error_classes() if get_redis_error_classes
            else ((), ()))

    def get(self, key):
        return self.client.get(key)

    def mget(self, keys):
        return self.client.mget(keys)

    def ensure(self, fun, args, **policy):
        retry_policy = dict(self.retry_policy, **policy)
        max_retries = retry_policy.get('max_retries')
        return retry_over_time(
            fun, self.connection_errors, args, {},
            partial(self.on_connection_error, max_retries),
            **retry_policy
        )

    def on_connection_error(self, max_retries, exc, intervals, retries):
        tts = next(intervals)
        error('Connection to Redis lost: Retry (%s/%s) %s.',
              retries, max_retries or 'Inf',
              humanize_seconds(tts, 'in '))
        return tts

    def set(self, key, value, **retry_policy):
        return self.ensure(self._set, (key, value), **retry_policy)

    def _set(self, key, value):
        with self.client.pipeline() as pipe:
            if self.expires:
                pipe.setex(key, self.expires, value)
            else:
                pipe.set(key, value)
            pipe.execute()

    def delete(self, key):
        self.client.delete(key)

    def incr(self, key):
        return self.client.incr(key)

    def expire(self, key, value):
        return self.client.expire(key, value)

    def add_to_chord(self, group_id, result):
        self.client.incr(self.get_key_for_group(group_id, '.t'), 1)

    def _unpack_chord_result(self, tup, decode,
                             EXCEPTION_STATES=states.EXCEPTION_STATES,
                             PROPAGATE_STATES=states.PROPAGATE_STATES):
        _, tid, state, retval = decode(tup)
        if state in EXCEPTION_STATES:
            retval = self.exception_to_python(retval)
        if state in PROPAGATE_STATES:
            raise ChordError('Dependency {0} raised {1!r}'.format(tid, retval))
        return retval

    def on_chord_part_return(self, request, state, result,
                             propagate=None, **kwargs):
        app = self.app
        tid, gid, group_index = request.id, request.group, request.group_index
        if not gid or not tid:
            return
        if group_index is None:
            group_index = '+inf'

        client = self.client
        jkey = self.get_key_for_group(gid, '.j')
        tkey = self.get_key_for_group(gid, '.t')
        result = self.encode_result(result, state)
        with client.pipeline() as pipe:
            if self._chord_zset:
                pipeline = (
                    pipe.zadd(
                        jkey,
                        {
                            self.encode([1, tid, state, result]): group_index
                        }
                    ).zcount(jkey, '-inf', '+inf')
                )
            else:
                pipeline = (
                    pipe.rpush(
                        jkey,
                        self.encode([1, tid, state, result])).llen(jkey)
                )
            pipeline = pipeline.get(tkey)

            if self.expires is not None:
                pipeline = pipeline \
                    .expire(jkey, self.expires) \
                    .expire(tkey, self.expires)

            _, readycount, totaldiff = pipeline.execute()[:3]

        totaldiff = int(totaldiff or 0)

        try:
            callback = maybe_signature(request.chord, app=app)
            total = callback['chord_size'] + totaldiff
            if readycount == total:
                decode, unpack = self.decode, self._unpack_chord_result
                with client.pipeline() as pipe:
                    if self._chord_zset:
                        pipeline = pipe.zrange(jkey, 0, -1)
                    else:
                        pipeline = pipe.lrange(jkey, 0, total)
                    resl, = pipeline.execute()
                try:
                    callback.delay([unpack(tup, decode) for tup in resl])
                    with client.pipeline() as pipe:
                        _, _ = pipe \
                            .delete(jkey) \
                            .delete(tkey) \
                            .execute()
                except Exception as exc:  # pylint: disable=broad-except
                    logger.exception(
                        'Chord callback for %r raised: %r', request.group, exc)
                    return self.chord_error_from_stack(
                        callback,
                        ChordError('Callback error: {0!r}'.format(exc)),
                    )
        except ChordError as exc:
            logger.exception('Chord %r raised: %r', request.group, exc)
            return self.chord_error_from_stack(callback, exc)
        except Exception as exc:  # pylint: disable=broad-except
            logger.exception('Chord %r raised: %r', request.group, exc)
            return self.chord_error_from_stack(
                callback,
                ChordError('Join error: {0!r}'.format(exc)),
            )

    @cached_property
    def client(self):
        return RedisCluster(**self.conn_params)

    def __reduce__(self, args=(), kwargs={}):
        return super(RedisClusterBackend, self).__reduce__(
            (self.conn_params['startup_nodes'], self.conn_params['password']), {
                'expires': self.expires},
        )
