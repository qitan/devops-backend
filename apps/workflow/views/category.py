import django_filters
from rest_framework import pagination
from rest_framework.decorators import action
from rest_framework.response import Response

from common.extends.filters import CustomSearchFilter
from common.extends.permissions import RbacPermission
from common.extends.viewsets import CustomModelViewSet
from dbapp.models import WorkflowCategory
from workflow.serializers import WorkflowCategorySerializer, WorkflowTemplateSerializer

from rest_framework.filters import OrderingFilter
import logging

logger = logging.getLogger(__name__)


class WorkflowCategoryViewSet(CustomModelViewSet):
    """
    工单分类视图
    ### 工单分类视图权限
        {'*': ('admin', '管理员')},
        {'*': ('workflow_category_all', '工单分类管理')},
        {'get': ('workflow_category_list', '查看工单分类')},
        {'post': ('workflow_category_create', '创建工单分类')},
        {'put': ('workflow_category_edit', '编辑工单分类')},
        {'delete': ('workflow_category_delete', '删除工单分类')}
    """
    perms_map = (
        {'*': ('admin', '管理员')},
        {'*': ('workflow_category_all', '工单分类管理')},
        {'get': ('workflow_category_list', '查看工单分类')},
        {'post': ('workflow_category_create', '创建工单分类')},
        {'put': ('workflow_category_edit', '编辑工单分类')},
        {'delete': ('workflow_category_delete', '删除工单分类')}
    )
    queryset = WorkflowCategory.objects.all()
    serializer_class = WorkflowCategorySerializer
    filter_backends = (django_filters.rest_framework.DjangoFilterBackend,
                       CustomSearchFilter, OrderingFilter)
    filter_fields = ('name',)
    search_fields = ('name',)

    @action(methods=['GET'], url_path='template', detail=True)
    def category_ticket_template(self, request, pk=None):
        page_size = request.query_params.get('page_size')
        pagination.PageNumberPagination.page_size = page_size
        qs = self.queryset.get(pk=pk)
        queryset = qs.workflowtemplate_set.all()
        logger.debug('queryset === %s', queryset)
        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)
        serializer = WorkflowTemplateSerializer(queryset, many=True)
        logger.debug('page === %s', page)
        if page is not None:
            return self.get_paginated_response(serializer.data)
        return Response({
            'code': 20000,
            'status': 'success',
            'data': {
                'total': queryset.count(),
                'items': serializer.data
            }
        })
