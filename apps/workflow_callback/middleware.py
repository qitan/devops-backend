from django.http import HttpResponse
from django.utils.deprecation import MiddlewareMixin
import logging

logger = logging.getLogger(__name__)


class WorkflowCallbackMiddleware(MiddlewareMixin):
    def process_request(self, request):
        workflow_node_history_id = request.GET.get('__workflow_node_history_id__')
        if request.GET.get('__workflow_node_history_id__'):
            setattr(request, 'workflow_node_history_id', workflow_node_history_id)

    def process_exception(self, request, exception):
        if hasattr(request, 'workflow_node_history_id'):
            msg = f'工单回调发生异常： {exception.__class__} {exception}'
            logger.exception(f'工单回调发生异常 {exception}')
            return HttpResponse(msg, status=500)
        raise exception
