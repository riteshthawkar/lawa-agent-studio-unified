from django.urls import path, include
from rest_framework.routers import DefaultRouter
from . import views

router = DefaultRouter()
router.register(r'chat/sessions', views.ChatSessionViewSet, basename='chat-session')

urlpatterns = [
    path('', include(router.urls)),
    path('chat/sessions/<uuid:session_id>/send/', views.send_message, name='send-message'),
    path('chat/sessions/<uuid:session_id>/messages/', views.session_messages, name='session-messages'),
    path('chat/sessions/<uuid:session_id>/close/', views.close_session, name='close-session'),
    # Feedback endpoints
    path('chat/messages/<uuid:message_id>/feedback/', views.submit_feedback, name='submit-feedback'),
    path('chat/messages/<uuid:message_id>/feedback', views.message_feedback, name='message-feedback'),
    path('chat/sessions/<uuid:session_id>/feedback-stats/', views.session_feedback_stats, name='session-feedback-stats'),
]
