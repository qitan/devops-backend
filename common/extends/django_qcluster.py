#!/usr/bin/env python
# -*- encoding: utf-8 -*-
'''
@author  :   Charles Lai
@file    :   django_qcluster.py
@time    :   2023/03/08 21:21
@contact :   qqing_lai@hotmail.com
@company :   IMAOJIA Co,Ltd
'''

# here put the import lib
from time import sleep
from multiprocessing import current_process, Event, Process
from django.utils.translation import gettext_lazy as _
from django_q.brokers import Broker
from django_q.humanhash import humanize
from django_q.status import Stat
from django_q.cluster import scheduler, Cluster as BaseCluster, Sentinel as BaseSentinel
from django_q.conf import (
    Conf, 
    logger
)


class Sentinel(BaseSentinel):

    def __init__(self, stop_event, start_event, cluster_id, broker=None, timeout=Conf.TIMEOUT, start=True):
        super().__init__(stop_event, start_event, cluster_id, broker, timeout, start)

    def guard(self):
        logger.info(
            _(
                f"{current_process().name} guarding cluster {humanize(self.cluster_id.hex)}"
            )
        )
        self.start_event.set()
        Stat(self).save()
        logger.info(_(f"Q Cluster {humanize(self.cluster_id.hex)} running."))
        counter = 0
        cycle = Conf.GUARD_CYCLE  # guard loop sleep in seconds, 默认0.5
        # Guard loop. Runs at least once
        while not self.stop_event.is_set() or not counter:
            # Check Workers
            for p in self.pool:
                with p.timer.get_lock():
                    # Are you alive?
                    if not p.is_alive() or p.timer.value == 0:
                        self.reincarnate(p)
                        continue
                    # Decrement timer if work is being done
                    if p.timer.value > 0:
                        p.timer.value -= cycle
            # Check Monitor
            if not self.monitor.is_alive():
                self.reincarnate(self.monitor)
            # Check Pusher
            if not self.pusher.is_alive():
                self.reincarnate(self.pusher)
            # Call scheduler once a minute (or so)
            counter += cycle
            # 默认30
            if counter >= 10 and Conf.SCHEDULER:
                counter = 0
                scheduler(broker=self.broker)
            # Save current status
            Stat(self).save()
            sleep(cycle)
        self.stop()


class Cluster(BaseCluster):
    
    def __init__(self, broker: Broker = None):
        super().__init__(broker)

    def start(self) -> int:
        # Start Sentinel
        self.stop_event = Event()
        self.start_event = Event()
        self.sentinel = Process(
            target=Sentinel,
            args=(
                self.stop_event,
                self.start_event,
                self.cluster_id,
                self.broker,
                self.timeout,
            ),
        )
        self.sentinel.start()
        logger.info(_(f"Q Cluster {self.name} starting."))
        while not self.start_event.is_set():
            sleep(0.1)
        return self.pid
