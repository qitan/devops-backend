#!/usr/bin/env python
# -*- coding:utf-8 -*-
# @Author: Charles Lai
# @Email: qqing_lai@hotmail.com
# @Site: https://imaojia.com
# @File: MailSend.py
# @Time: 18-3-7 下午1:48

from fernet_fields import EncryptedField
from django.core.mail import send_mail
from django.core.mail import send_mass_mail
from django.core.mail.backends.smtp import EmailBackend as BaseEmailBackend
from django.conf import settings

from dbapp.models import SystemConfig

from common.utils.RedisAPI import RedisManage
from common.ext_fun import get_redis_data

import threading
import json
import logging

logger = logging.getLogger(__name__)

TICKET_STATUS = {0: '', 1: '', 2: '需要审批', 3: '审批通过，待执行', 4: '执行中', 5: '已处理完成，请前往平台确认是否结单',
                 6: '审批不通过', 7: '申请被驳回',
                 8: '因用户对处理结果有异议，请重新处理', 9: '用户已确认结单'}


def check_key(key, data):
    if key in data:
        return data[key]
    else:
        return None


class EmailBackend(BaseEmailBackend):
    """
    A wrapper that manages the SMTP network connection.
    """

    def __init__(self, host=None, port=None, username=None, password=None,
                 use_tls=None, fail_silently=False, use_ssl=None, timeout=None,
                 ssl_keyfile=None, ssl_certfile=None,
                 **kwargs):
        super().__init__(fail_silently=fail_silently)
        self.mail_config = get_redis_data('mail')
        self.host = host or check_key(
            'host', self.mail_config) or settings.EMAIL_HOST
        self.port = port or check_key(
            'port', self.mail_config) or settings.EMAIL_PORT
        self.username = check_key('user',
                                  self.mail_config) or settings.EMAIL_HOST_USER if username is None else username
        self.password = check_key('password',
                                  self.mail_config) or settings.EMAIL_HOST_PASSWORD if password is None else password
        self.use_tls = check_key(
            'tls', self.mail_config) or settings.EMAIL_USE_TLS if use_tls is None else use_tls
        self.use_ssl = check_key(
            'ssl', self.mail_config) or settings.EMAIL_USE_SSL if use_ssl is None else use_ssl
        self.timeout = check_key(
            'timeout', self.mail_config) or settings.EMAIL_TIMEOUT if timeout is None else timeout
        self.ssl_keyfile = check_key('key',
                                     self.mail_config) or settings.EMAIL_SSL_KEYFILE if ssl_keyfile is None else ssl_keyfile
        self.ssl_certfile = check_key('cert',
                                      self.mail_config) or settings.EMAIL_SSL_CERTFILE if ssl_certfile is None else ssl_certfile
        if self.use_ssl and self.use_tls:
            raise ValueError(
                "EMAIL_USE_TLS/EMAIL_USE_SSL are mutually exclusive, so only set "
                "one of those settings to True.")
        self.connection = None
        self._lock = threading.RLock()


class OmsMail(object):
    def __init__(self):
        self.__email_config = get_redis_data('mail')
        self.__master = None
        if self.__email_config:
            self.__master = self.__email_config.get('user', None)
        self.__url = get_redis_data('platform')['url']

    def send_mail(self, title, msg, receiver, is_html=False):
        self.__send_mail(title, msg, receiver, is_html=is_html)

    def __send_mail(self, title, msg, receiver, is_html=False):
        """

        :param title:
        :param msg:
        :param receiver: 'a@yd.com,b@yd.com'
        :return:
        """
        try:
            html_message = ''
            if is_html:
                html_message = msg
            send_mail(
                f"{self.__email_config['prefix']}{title}",
                msg,
                self.__master, receiver.split(','),
                html_message=html_message
            )
            return {'status': 0}
        except Exception as e:
            print('err', e)
            return {'status': 1, 'msg': '发送邮件通知失败 %s' % str(e)}

    def ticket_process(self, ticket, title, status, user, receiver):
        msg = f"Hi {user}，\n你有新的工单{ticket}（标题：{title}）{TICKET_STATUS[status]}。\n请访问{self.__url} 进行处理。"
        self.__send_mail('工单跟踪', msg, receiver)

    def ticket_handle(self, ticket, title, status, user, receiver):
        msg = f"Hi {user}，\n工单{ticket}（标题：{title}）{TICKET_STATUS[status]}。\n请访问{self.__url} 进行处理。"
        self.__send_mail('工单跟踪', msg, receiver)

    def ticket_create(self, ticket, title, status, user, receiver):
        mail_title = '工单处理结果'
        if status == 4:
            mail_title = '工单处理中'
        msg = f"Hi {user}，\n你的工单{ticket}（标题：{title}）{TICKET_STATUS[status]}。\n请访问{self.__url} 查看更多信息。"
        self.__send_mail(mail_title, msg, receiver)

    def account_register(self, op_user, username, password, user, receiver):
        msg = f"Hi {user}，\n{op_user}已为你开通平台账号，相关信息如下：\n用户名：{username}\n密码：{password}\n登录地址：{self.__url}。"
        self.__send_mail('账号开通', msg, receiver)

    def deploy_notify(self, title, msg, receiver):
        self.__send_mail(title, msg, receiver)

    def test_notify(self, receiver):
        ret = self.__send_mail('邮件测试', "Hi，如果能看到此邮件，说明平台邮件服务配置成功", receiver)
        return ret
