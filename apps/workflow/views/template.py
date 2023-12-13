import django_filters
from rest_framework.filters import OrderingFilter

from common.extends.filters import CustomSearchFilter
from common.extends.permissions import RbacPermission
from common.extends.viewsets import CustomModelViewSet
from dbapp.models import WorkflowTemplate
from workflow.serializers import WorkflowTemplateSerializer

import logging

logger = logging.getLogger(__name__)


class WorkflowTemplateViewSet(CustomModelViewSet):
    """
    工单模板
    ### 工单模板权限
        {'*': ('admin', '管理员')},
        {'*': ('workflow_template_all', '工单模板管理')},
        {'get': ('workflow_template_list', '查看工单模板')},
        {'post': ('workflow_template_create', '创建工单模板')},
        {'put': ('workflow_template_edit', '编辑工单模板')},
        {'delete': ('workflow_template_delete', '删除工单模板')}
    """
    perms_map = (
        {'*': ('admin', '管理员')},
        {'*': ('workflow_template_all', '工单模板管理')},
        {'get': ('workflow_template_list', '查看工单模板')},
        {'post': ('workflow_template_create', '创建工单模板')},
        {'put': ('workflow_template_edit', '编辑工单模板')},
        {'delete': ('workflow_template_delete', '删除工单模板')}
    )
    queryset = WorkflowTemplate.objects.all()
    serializer_class = WorkflowTemplateSerializer
    filter_backends = (django_filters.rest_framework.DjangoFilterBackend,
                       CustomSearchFilter, OrderingFilter)
    filter_fields = ('category', 'enabled',)
    search_fields = ('name',)

    def get_serializer_context(self):
        """
        Extra context provided to the serializer class.
        """
        return {
            'request': self.request,
            'format': self.format_kwarg,
            'view': self
        }

    def update(self, request, *args, **kwargs):
        response = super().update(request, *args, **kwargs)
        # 更新一下版本号
        if response.data['status'] == 'success':
            filters = {'pk': kwargs['pk']}
            instance = self.queryset.get(**filters)
            instance.revision = instance.revision + 1
            instance.save()
        return response
