from workflow.views.workflow import WorkflowViewSetAbstract, check_user_is_workflow_member

from dbapp.models import WorkflowNodeHistory
import logging

logger = logging.getLogger(__name__)


class WorkflowMyRelatedViewSet(WorkflowViewSetAbstract):
    """
    我的关联

    ### 我的关联 权限
        {'*': ('admin', '管理员')},
        {'*': ('workflow_all', '工单管理')},
        {'get': ('workflow_my_relate_list', '查看我关联的工单')},
    """
    perms_map = (
        {'*': ('admin', '管理员')},
        {'*': ('workflow_all', '工单管理')},
        {'get': ('workflow_my_relate_list', '查看我关联的工单')},
    )

    def extend_filter(self, queryset):
        return self._get_node_include_me_workflow(queryset)

    def _get_node_include_me_workflow(self, queryset):
        """
        """
        match_id_list = []
        user_obj = self.request.user
        for i in queryset:
            if check_user_is_workflow_member(i, user_obj) or WorkflowNodeHistory.objects.filter(
                    workflow=i,
                    operator=self.request.user
            ).count() > 0:
                match_id_list.append(i.id)
        return queryset.filter(id__in=match_id_list)
