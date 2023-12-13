#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
@Author : Charles Lai
@Contact : qqing_lai@hotmail.com
@Time : 2021/1/20 下午2:24
@FileName: AesCipher.py
@Blog ：https://imaojia.com
"""

import base64
from Crypto.Cipher import AES


class AesCipher(object):
    def __init__(self, secret_key='Devops SecretKey'):
        self.__secret_key = secret_key
        self.__aes = AES.new(str.encode(self.__secret_key), AES.MODE_ECB)

    def encrypt(self, data):
        while len(data) % 16 != 0:  # 补足字符串长度为16的倍数
            data += (16 - len(data) % 16) * chr(16 - len(data) % 16)
        cipher_data = str(base64.encodebytes(self.__aes.encrypt(str.encode(data))), encoding='utf8').replace('\n', '')
        return cipher_data

    def decrypt(self, cipher_data):
        try:
            decrypted_text = self.__aes.decrypt(base64.decodebytes(bytes(cipher_data, encoding='utf8'))).decode("utf8")
            decrypted_text = decrypted_text[:-ord(decrypted_text[-1])]  # 去除多余补位
            return decrypted_text
        except BaseException as e:
            print('data', e)
            raise Exception(e)
