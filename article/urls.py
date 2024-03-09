from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import ArticleViewSet,CategoryViewSet

router = DefaultRouter()
router.register(r'list', ArticleViewSet)
router.register(r'categories', CategoryViewSet)

urlpatterns = [
    path('', include(router.urls)),
    path('<int:pk>/reviews/', ArticleViewSet.as_view({'get': 'get_reviews_by_article', 'post': 'create_review'}))
]