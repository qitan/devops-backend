#!/usr/bin/env python
# -*- encoding: utf-8 -*-
'''
@author  :   Charles Lai
@file    :   signals.py
@time    :   2023/04/20 17:49
@contact :   qqing_lai@hotmail.com
'''

# here put the import lib
from django.db.models.signals import pre_save, post_save, post_delete
from django.dispatch import receiver

from dbapp.model.model_deploy import BuildJob, DeployJob, PublishApp
from deploy.rds_transfer import rds_transfer_es
from devops_backend import documents


import logging

logger = logging.getLogger('elasticsearch')


@receiver(post_save, sender=PublishApp, dispatch_uid='publishapp_record')
@receiver(post_save, sender=DeployJob, dispatch_uid='deployjob_record')
@receiver(post_save, sender=BuildJob, dispatch_uid='buildjob_record')
def save_es_record(sender, instance, created, **kwargs):
    if created is False or sender._meta.object_name == 'PublishApp':
        document = getattr(documents, f"{sender._meta.object_name}Document")
        try:
            rds_transfer_es(document, instance)
        except BaseException as e:
            logger.error(f'模型转存ES失败，原因：{e}')
