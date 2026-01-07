from django.urls import path, include
from rest_framework.routers import DefaultRouter
from . import views

router = DefaultRouter()
router.register(r'chatbots', views.ChatbotViewSet, basename='chatbot')

urlpatterns = [
    # Chatbot management
    path('', include(router.urls)),
    path('sites/<uuid:site_id>/chatbots/', views.ChatbotViewSet.as_view({'post': 'create'}), name='site-chatbot-create'),

    # Chatbot integration endpoints
    path('chatbot/index-info/', views.chatbot_index_info, name='chatbot-index-info'),
    path('chatbots/<uuid:chatbot_id>/embed-code/', views.chatbot_embed_code, name='chatbot-embed-code'),
    path('chatbots/<uuid:chatbot_id>/regenerate-api-key/', views.regenerate_api_key, name='chatbot-regenerate-api-key'),
    path('chatbots/<uuid:chatbot_id>/regenerate-embed-code/', views.regenerate_embed_code, name='chatbot-regenerate-embed-code'),

    # Conversation Starters - Management (authenticated)
    path('chatbots/<uuid:chatbot_id>/starters/', views.list_conversation_starters, name='list-starters'),
    path('chatbots/<uuid:chatbot_id>/starters/create/', views.create_conversation_starter, name='create-starter'),
    path('chatbots/<uuid:chatbot_id>/starters/bulk/', views.bulk_create_starters, name='bulk-create-starters'),
    path('chatbots/<uuid:chatbot_id>/starters/reorder/', views.reorder_starters, name='reorder-starters'),
    path('starters/<uuid:starter_id>/', views.conversation_starter_detail, name='starter-detail'),
    path('starters/<uuid:starter_id>/toggle/', views.toggle_starter, name='toggle-starter'),

    # Conversation Starters - Public (for widget)
    path('starters/<uuid:starter_id>/click/', views.track_starter_click, name='track-starter-click'),
    path('chatbot/<str:api_key>/starters/', views.public_starters, name='public-starters'),

    # Query Categories - Management (authenticated)
    path('chatbots/<uuid:chatbot_id>/categories/', views.list_query_categories, name='list-categories'),
    path('chatbots/<uuid:chatbot_id>/categories/create/', views.create_query_category, name='create-category'),
    path('chatbots/<uuid:chatbot_id>/categories/bulk/', views.bulk_create_categories, name='bulk-create-categories'),
    path('chatbots/<uuid:chatbot_id>/categories/reorder/', views.reorder_categories, name='reorder-categories'),
    path('categories/<uuid:category_id>/', views.query_category_detail, name='category-detail'),
    path('categories/<uuid:category_id>/toggle/', views.toggle_category, name='toggle-category'),

    # Query Categories - Public (for embedded chatbot backend)
    path('chatbot/<str:api_key>/categories/', views.public_categories, name='public-categories'),
]
