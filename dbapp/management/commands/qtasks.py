#!/usr/bin/env python
# -*- encoding: utf-8 -*-
'''
@author  :   Charles Lai
@file    :   qtasks.py
@time    :   2023/03/08 21:20
@contact :   qqing_lai@hotmail.com
@company :   IMAOJIA Co,Ltd
'''

# here put the import lib
from django.core.management.base import BaseCommand
from django.utils.translation import gettext as _

from common.extends.django_qcluster import Cluster


class Command(BaseCommand):
    # Translators: help text for qcluster management command
    help = _("Starts a Django Q Cluster.")

    def add_arguments(self, parser):
        parser.add_argument(
            "--run-once",
            action="store_true",
            dest="run_once",
            default=False,
            help="Run once and then stop.",
        )

    def handle(self, *args, **options):
        q = Cluster()
        q.start()
        if options.get("run_once", False):
            q.stop()
