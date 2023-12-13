from django.db import transaction
from dbapp.models import MicroApp
from common.ext_fun import get_datadict, get_members
from dbapp.models import UserProfile, DataDict
from workflow_callback.views.base import CallbackAPIView
from rest_framework.response import Response
from dbapp.models import Workflow

from asgiref.sync import sync_to_async
from channels.db import database_sync_to_async
import logging

logger = logging.getLogger(__name__)


class AppMemberAPIView(CallbackAPIView):

    @transaction.atomic
    def post(self, request):
        data = request.data
        first_node_form = data['first_node_form']
        app_node = first_node_form.get('申请应用')
        app_value = app_node.get('applist', [])
        position = app_node.get('position', None)
        if not app_value:
            return Response('缺少 申请应用 参数', status=400)
        user_value = first_node_form.get('申请用户')
        if not user_value:
            return Response('缺少 申请用户 参数', status=400)

        # 获取工单
        wf = self.get_workflow(request)
        user_value = list(map(lambda x: x.split('@')[0], user_value))
        app_objs = MicroApp.objects.filter(appid__in=app_value)
        user_objs = UserProfile.objects.filter(username__in=user_value)
        response_texts = []
        init_point = transaction.savepoint()
        for app_obj in app_objs:
            for user_obj in user_objs:
                if user_obj.is_superuser:
                    user_position = 'op'
                else:
                    positions = get_datadict('POSITION', config=1)
                    user_obj.position = position
                    user_obj.save()
                    user_position = user_obj.position
                    if user_position not in [i['name'] for i in positions]:
                        response_texts.append(
                            f'{app_obj}  用户 {user_obj} position 不在映射中： {user_position}')
                        continue
                member_list = app_obj.team_members.get(user_position, [])
                if user_obj.id in member_list:
                    response_texts.append(
                        f'{app_obj}  {user_position} 用户已经存在：{user_obj}')
                    continue
                member_list.append(user_obj.id)
                response_texts.append(
                    f'{app_obj}  {user_position} 添加用户：{user_obj}')
            app_obj.save()
        response_text = "<br />".join(response_texts)
        self.set_status(wf, 'complete')
        return Response(f'执行完毕<br /> {response_text}')
