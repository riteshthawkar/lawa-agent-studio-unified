"""
URL configuration for support app
"""
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from . import views

router = DefaultRouter()
router.register(r'faq-categories', views.FAQCategoryViewSet, basename='faq-category')
router.register(r'faqs', views.FAQViewSet, basename='faq')
router.register(r'feedback', views.FeedbackViewSet, basename='feedback')
router.register(r'help-articles', views.HelpArticleViewSet, basename='help-article')

urlpatterns = [
    path('', include(router.urls)),
]
