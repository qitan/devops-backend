from rest_framework import exceptions
from rest_framework.authentication import CSRFCheck
from rest_framework_simplejwt.authentication import JWTAuthentication
from django.conf import settings
from rest_framework_simplejwt.settings import api_settings

import logging

logger = logging.getLogger(__name__)


class CookiesAuthentication(JWTAuthentication):
    cookieName = 'visionToken'

    def authenticate(self, request):
        raw_token = request.COOKIES.get(self.cookieName) or None
        if raw_token is None:
            return None

        validated_token = self.get_validated_token(raw_token)
        return self.get_user(validated_token), validated_token
