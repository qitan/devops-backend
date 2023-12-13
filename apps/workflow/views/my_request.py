from workflow.views.workflow import WorkflowViewSetAbstract

from workflow.serializers import WorkflowListSerializer


class WorkflowMyRequestViewSet(WorkflowViewSetAbstract):
    """
    我的请求

    ### 工单 我的请求 权限
        {'*': ('admin', '管理员')},
        {'*': ('workflow_all', '工单管理')},
        {'get': ('workflow_my_request_list', '查看我创建的工单')},
    """
    perms_map = (
        {'*': ('admin', '管理员')},
        {'*': ('workflow_all', '工单管理')},
        {'get': ('workflow_my_request_list', '查看我创建的工单')},
    )
    serializer_list_class = WorkflowListSerializer

    def extend_filter(self, queryset):
        return queryset.filter(creator=self.request.user.id)
