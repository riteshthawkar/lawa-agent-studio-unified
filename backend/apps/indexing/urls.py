from django.urls import path, include
from rest_framework.routers import DefaultRouter
from . import views

router = DefaultRouter()
router.register(r'indexing-jobs', views.IndexingJobViewSet, basename='indexing-job')

urlpatterns = [
    # Existing endpoints
    path('', include(router.urls)),
    path('sites/<uuid:site_id>/indexing-jobs/', views.site_indexing_jobs, name='site-indexing-jobs'),
    path('indexing-jobs/<uuid:job_id>/', views.indexing_job_detail, name='indexing-job-detail'),

    # API Specification Compliant Endpoints
    path('tasks/', views.tasks_list, name='tasks-list'),
    path('tasks/<str:task_id>/', views.task_detail, name='task-detail'),
    path('tasks/<str:task_id>/cancel/', views.cancel_task, name='cancel-task'),
    path('health/', views.health_check, name='health-check'),
    path('stats/', views.service_stats, name='service-stats'),
    path('index/', views.start_indexing, name='start-indexing'),

    # Bug #26 fix: IndexedPage endpoints for per-URL visibility
    path('sites/<uuid:site_id>/indexed-pages/', views.site_indexed_pages, name='site-indexed-pages'),
    path('sites/<uuid:site_id>/indexed-pages/add/', views.add_indexed_page, name='add-indexed-page'),
    # P3.1: Bulk delete indexed pages
    path('sites/<uuid:site_id>/indexed-pages/bulk-delete/', views.bulk_delete_indexed_pages, name='bulk-delete-indexed-pages'),
    path('indexed-pages/<uuid:page_id>/', views.indexed_page_detail, name='indexed-page-detail'),
    path('indexed-pages/<uuid:page_id>/delete/', views.delete_indexed_page, name='delete-indexed-page'),
]

