#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
@Author  : Charles Lai
@Contact : qqing_lai@hotmail.com
@Time    : 2020/7/2 上午11:00
@FileName: JwtAuth.py
@Company : Vision Fund
"""

from __future__ import unicode_literals

from rest_framework import exceptions, status
from rest_framework_simplejwt.authentication import JWTAuthentication as BaseJWTAuthentication
from rest_framework_simplejwt.exceptions import TokenError, InvalidToken
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer as BaseTokenObtainPairSerializer, \
    TokenRefreshSerializer as BaseTokenRefreshSerializer
from rest_framework_simplejwt.tokens import Token as BaseToken, RefreshToken as BaseRefreshToken
from rest_framework_simplejwt.settings import APISettings, DEFAULTS, IMPORT_STRINGS
from django.utils.translation import ugettext_lazy as _

from devops_backend import settings

from common.ext_fun import get_redis_data
import datetime

api_settings = APISettings(
    getattr(settings, 'SIMPLE_JWT', None), DEFAULTS, IMPORT_STRINGS)


class JWTAuthentication(BaseJWTAuthentication):
    """
    code: 40108 登录失败，40101 刷新Token失效，40100 Token已经过期
    """

    def get_validated_token(self, raw_token):
        """
        Validates an encoded JSON web token and returns a validated token
        wrapper object.
        """
        messages = []
        for AuthToken in api_settings.AUTH_TOKEN_CLASSES:
            try:
                return AuthToken(raw_token)
            except TokenError as e:
                messages.append(
                    {
                        "token_class": AuthToken.__name__,
                        "token_type": AuthToken.token_type,
                        "message": e.args[0],
                    }
                )

        raise CustomInvalidToken(
            {
                "detail": 'Token已经过期.',
                "code": 40100
            }
        )


class CustomInvalidToken(InvalidToken):
    status_code = status.HTTP_401_UNAUTHORIZED
    default_detail = 'Token不合法或者已经过期.'
    default_code = 40100


class AccessToken(BaseToken):
    token_type = 'access'

    def __init__(self, token=None, verify=True):
        expired_time = get_redis_data('platform')
        lifetime = datetime.timedelta(minutes=expired_time[
            'access']) if expired_time and 'access' in expired_time else api_settings.ACCESS_TOKEN_LIFETIME
        self.lifetime = lifetime
        super().__init__(token, verify)


class RefreshToken(BaseRefreshToken):
    token_type = 'refresh'

    def __init__(self, token=None, verify=True):
        expired_time = get_redis_data('platform')
        lifetime = datetime.timedelta(minutes=expired_time[
            'refresh']) if expired_time and 'refresh' in expired_time else api_settings.REFRESH_TOKEN_LIFETIME
        self.lifetime = lifetime
        super().__init__(token, verify)

    @property
    def access_token(self):
        """
        Returns an access token created from this refresh token.  Copies all
        claims present in this refresh token to the new access token except
        those claims listed in the `no_copy_claims` attribute.
        """
        access = AccessToken()
        access.set_exp(from_time=self.current_time)

        no_copy = self.no_copy_claims
        for claim, value in self.payload.items():
            if claim in no_copy:
                continue
            access[claim] = value

        return access


class TokenRefreshSerializer(BaseTokenRefreshSerializer):

    def validate(self, attrs):
        refresh = RefreshToken(attrs['refresh'])
        data = {'access': str(refresh.access_token)}

        if api_settings.ROTATE_REFRESH_TOKENS:
            if api_settings.BLACKLIST_AFTER_ROTATION:
                try:
                    # Attempt to blacklist the given refresh token
                    refresh.blacklist()
                except AttributeError:
                    # If blacklist app not installed, `blacklist` method will
                    # not be present
                    pass

            refresh.set_jti()
            refresh.set_exp()

            data['refresh'] = str(refresh)

        return data


class TokenObtainPairSerializer(BaseTokenObtainPairSerializer):

    default_error_messages = {
        "no_active_account": "用户名或者密码错误！"
    }

    @classmethod
    def get_token(cls, user):
        token = RefreshToken.for_user(user)
        return token
