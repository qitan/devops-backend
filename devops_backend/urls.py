"""devops_backend URL Configuration

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/3.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from config import DEBUG
from django.contrib import admin
from django.urls import path, include

from rest_framework.documentation import include_docs_urls
from rest_framework.routers import DefaultRouter
from rest_framework import permissions

from drf_yasg.views import get_schema_view
from drf_yasg import openapi

from ucenter.views import SystemConfigViewSet, MenuViewSet, PermissionViewSet, RoleViewSet, OrganizationViewSet, \
    UserViewSet, UserProfileViewSet, UserAuthTokenView, UserLogout, UserAuthTokenRefreshView, AuditLogViewSet, \
    DataDictViewSet
from dashboard.views import LiveCheck
from deploy.views import BuildJobViewSet, PublishOrderViewSet, PublishAppViewSet, \
    DeployJobViewSet
from workflow.views.callback import WorkflowNodeHistoryCallbackViewSet
from workflow.views.workflow import WorkflowViewSet
from workflow.views.my_related import WorkflowMyRelatedViewSet
from workflow.views.my_request import WorkflowMyRequestViewSet
from workflow.views.my_upcoming import WorkflowMyUpComingViewSet
from workflow.views.template import WorkflowTemplateViewSet
from workflow.views.category import WorkflowCategoryViewSet

from cmdb import urls as cmdb_urls
from dashboard import urls as dashboard_urls
from workflow_callback import urls as workflow_callback_urls

schema_view = get_schema_view(
    openapi.Info(
        title="DevOps运维平台",
        default_version='v1',
        description="DevOps运维平台 接口文档",
        terms_of_service="",
        contact=openapi.Contact(email="qqing_lai@hotmail.com"),
        license=openapi.License(name="Apache License 2.0"),
    ),
    public=True,
    permission_classes=(permissions.IsAuthenticated, )
)

router = DefaultRouter()
router.register('cicd/order/app', PublishAppViewSet)
router.register('cicd/order', PublishOrderViewSet)
router.register('cicd/deploy', DeployJobViewSet)
router.register('cicd', BuildJobViewSet)
# ucenter
router.register('audit', AuditLogViewSet)
router.register('system/data', DataDictViewSet)
router.register('system', SystemConfigViewSet)
router.register('menu', MenuViewSet)
router.register('permission', PermissionViewSet)
router.register('role', RoleViewSet)
router.register('organization', OrganizationViewSet)
router.register('users', UserViewSet)
router.register('user/profile', UserProfileViewSet, basename='user-profile')
# 新的工单系统
router.register('workflow/node_history/callback',
                WorkflowNodeHistoryCallbackViewSet)
router.register('workflow/category', WorkflowCategoryViewSet)
router.register('workflow/template', WorkflowTemplateViewSet)
router.register('workflow/my-request', WorkflowMyRequestViewSet)
router.register('workflow/my-upcoming', WorkflowMyUpComingViewSet)
router.register('workflow/my-related', WorkflowMyRelatedViewSet)
router.register('workflow', WorkflowViewSet)

extra = '/'

urlpatterns = [
    path('admin/', admin.site.urls),
    path('apidoc/', schema_view.with_ui('swagger',
         cache_timeout=0), name='schema-swagger-ui'),
    path('api/', include(router.urls)),
    path('api/workflow_callback/', include(workflow_callback_urls),
         name='workflow_callback'),
    path('api/check/', LiveCheck.as_view(), name='live-check'),
    path('api/user/login/', UserAuthTokenView.as_view(), name='user-login'),
    path('api/user/logout/', UserLogout.as_view(), name='user-logout'),
    path('api/user/refresh/', UserAuthTokenRefreshView.as_view(),
         name='token-refresh'),
    path('api/', include(cmdb_urls)),
    path('api/', include(dashboard_urls)),
]

if DEBUG:
    # 兼容gunicorn启动
    from django.contrib.staticfiles.urls import staticfiles_urlpatterns
    urlpatterns += staticfiles_urlpatterns()
