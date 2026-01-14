from django.urls import path, include
from rest_framework.routers import DefaultRouter
from . import views

router = DefaultRouter()
router.register(r'sites', views.SiteViewSet, basename='site')

urlpatterns = [
    path('', include(router.urls)),
    # MVP: Comment out verification endpoints
    # path('sites/<uuid:site_id>/verify/', views.verify_site, name='site-verify'),
    # path('sites/<uuid:site_id>/verification-instructions/', views.site_verification_instructions, name='site-verification-instructions'),

    # Excluded URL Pattern management
    path('sites/<uuid:site_id>/excluded-patterns/', views.site_excluded_patterns, name='site-excluded-patterns'),
    path('sites/<uuid:site_id>/excluded-patterns/add/', views.add_excluded_pattern, name='add-excluded-pattern'),
    path('sites/<uuid:site_id>/excluded-patterns/bulk/', views.bulk_add_excluded_patterns, name='bulk-add-excluded-patterns'),
    # P3.2/P3.3: Apply exclusions and preview impact
    path('sites/<uuid:site_id>/excluded-patterns/apply-now/', views.apply_exclusions_now, name='apply-exclusions-now'),
    path('sites/<uuid:site_id>/excluded-patterns/preview/', views.preview_exclusion_impact, name='preview-exclusion-impact'),
    # P4.2: Exclusion templates
    path('excluded-patterns/templates/', views.get_exclusion_templates, name='get-exclusion-templates'),
    path('sites/<uuid:site_id>/excluded-patterns/apply-template/', views.apply_template, name='apply-template'),
    path('excluded-patterns/<uuid:pattern_id>/', views.excluded_pattern_detail, name='excluded-pattern-detail'),
    path('excluded-patterns/<uuid:pattern_id>/toggle/', views.toggle_excluded_pattern, name='toggle-excluded-pattern'),
    path('excluded-patterns/<uuid:pattern_id>/test/', views.test_excluded_pattern, name='test-excluded-pattern'),
    # P4.1: Undo exclusion
    path('excluded-patterns/<uuid:pattern_id>/undo/', views.undo_exclusion, name='undo-exclusion'),
]

