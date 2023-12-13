#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
@Author : Charles Lai
@Contact : qqing_lai@hotmail.com
@Time : 2020/10/9 下午2:29
@FileName: websocket.py
@Blog ：https://imaojia.com
"""


async def websocket_application(scope, receive, send):
    while True:
        # print(scope)
        event = await receive()

        if event['type'] == 'websocket.connect':
            await send({
                'type': 'websocket.accept'
            })

        if event['type'] == 'websocket.disconnect':
            break

        if event['type'] == 'websocket.receive':
            print(scope['path'])
            if scope['path'] == '/build':
                await send({
                    'type': 'websocket.send',
                    'text': 'ws send'
                })
            if event['text'] == 'ping':
                await send({
                    'type': 'websocket.send',
                    'text': 'pong'
                })
