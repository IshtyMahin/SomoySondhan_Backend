"""Newsroom routes.

The explicit `/<pk>/reviews/` path keeps the exact URL the current frontend
calls; everything else comes from the router.
"""

from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import (
    ArticleViewSet,
    BookmarkViewSet,
    CategoryViewSet,
    CommentViewSet,
    ReviewViewSet,
    StatsView,
    TagViewSet,
)

router = DefaultRouter()
router.register(r"list", ArticleViewSet, basename="article")
router.register(r"categories", CategoryViewSet, basename="category")
router.register(r"tags", TagViewSet, basename="tag")
router.register(r"reviews", ReviewViewSet, basename="review")
router.register(r"comments", CommentViewSet, basename="comment")
router.register(r"bookmarks", BookmarkViewSet, basename="bookmark")
router.register(r"stats", StatsView, basename="stats")

urlpatterns = [
    # Declared before the router so it wins: the frontend posts reviews here.
    path(
        "<int:pk>/reviews/",
        ArticleViewSet.as_view({"get": "reviews", "post": "reviews"}),
        name="article-reviews",
    ),
    path("", include(router.urls)),
]
