from rest_framework.exceptions import APIException


class OkAPIException(APIException):
    """
    新增一个 异常类型
    因为接口返回状态重新封装过， stasus_code 都是200， 当需要引发一个 api 异常且需要返回数据的时候，比较麻烦
    为什么需要引发异常：
        好处1：
            能够搭配 transaction.atomic， 当 异常产生的时候， transaction.atomic会回滚数据，防止产生脏数据
    """
    status_code = 200
