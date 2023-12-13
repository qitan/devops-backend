from dbapp.models import UserProfile
from dbapp.models import WorkflowTemplate, Workflow
import requests

from common.ext_fun import get_redis_data
import logging

logger = logging.getLogger(__name__)


def callback_work(
        callback_type, method, url, template_model_cls=WorkflowTemplate,
        creator_id=None, wid=None, node_name=None, topic=None,
        template_id=None, cur_node_form=None, first_node_form=None,
        workflow_node_history_id=None,
        headers: dict = None, cookies: dict = None, action='normal', timeout=10
):
    url = url.strip()
    method = method.lower()
    if not headers:
        headers = {}
    if not cookies:
        cookies = {}
    params = {
        '__workflow_node_callback_type__': callback_type,
        '__workflow_node_history_id__': workflow_node_history_id
    }
    data = {'action': action}
    # api地址是来自本项目的情况和来自其他http服务的情况
    platform_conf = get_redis_data('platform')
    if '://' not in url:
        platform_base_url = platform_conf.get('url')
        if not platform_base_url:
            raise ValueError('获取不到平台访问地址， 请设置 【系统设置】-【基本设置】-【平台访问地址】')
        url = f'{platform_base_url.rstrip("/")}/{url.lstrip("/")}'  # 处理url地址
    template_obj = template_model_cls.objects.get(id=template_id)
    if not creator_id:
        creator_id = Workflow.objects.get(wid=wid).creator.id
    data['workflow'] = {
        'wid': wid,
        'name': topic,
        'template': template_obj.name,
        'node': node_name,
        'creator_id': creator_id,
    }
    data['cur_node_form'] = cur_node_form
    first_node_name = template_obj.nodes[0]['name']
    first_node_conf = template_obj.get_node_conf(first_node_name)
    form = {}
    for field_conf in first_node_conf['form_models']:
        name = field_conf['field']
        cname = field_conf['title']
        value = first_node_form.get(name, '')
        if name in first_node_form:
            form[cname] = value
    data['first_node_form'] = form
    data['node_name'] = first_node_name
    headers['Content-Type'] = 'application/json'

    is_exp, result, original_result = callback_request(method, url, headers=headers, params=params, json=data,
                                                       cookies=cookies, timeout=timeout)
    return {
        'type': callback_type,
        'url': url,
        'response': {
            'code': is_exp and 500 or original_result.status_code,
            'data': result
        }
    }


def callback_request(method, url, **kwargs):
    func = getattr(requests, method)
    if not func:
        msg = f'非法的 HTTP 方法名：{method}'
        return True, msg, None
    try:
        res = func(url, **kwargs)
        res_str = res.text.strip('"')
        logger.info(f'请求回调 {url} {kwargs.get("params")} 结果 {res_str}')
        return False, res_str, res
    except Exception as e:
        msg = f'请求回调 {url} 发生错误 {e.__class__} {e}'
        logger.exception(msg)
        return True, msg, e
