"""Newsroom API: articles, sections, tags, reviews, comments and bookmarks.

Endpoint map (the first four keep the shapes the current frontend expects):
  GET    /article/list/                     feed (plain array, or ?page=N envelope)
  GET    /article/list/<id>/                one story, with rating breakdown
  POST   /article/list/                     create (editors only)
  PATCH  /article/list/<id>/                update (editors only)
  DELETE /article/list/<id>/                delete (editors only)
  GET    /article/list/<id>/related/        same-section stories
  GET    /article/<id>/reviews/             read reviews
  POST   /article/<id>/reviews/             add a review (any signed-in reader)
  POST   /article/list/<id>/publish/        draft -> live
  POST   /article/list/<id>/archive/        take offline
  POST   /article/list/<id>/feature/        promote to the hero slot
  POST   /article/list/<id>/view/           count a read
  POST   /article/list/<id>/bookmark/       save/unsave
  GET    /article/categories/               sections
  GET    /article/tags/                     tags
  GET    /article/comments/                 comment stream (editors see the queue)
  GET    /article/bookmarks/                my saved stories
  GET    /article/stats/                    editorial dashboard
"""

import logging

from django.db.models import Count, Q
from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import SAFE_METHODS, AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle

from reader.permissions import IsEditorOrReadOnly, IsOwnerOrEditor

from .filters import ArticleFilter, CommentFilter
from .models import Article, ArticleView, Bookmark, Category, Comment, Review, Tag
from .pagination import wants_pagination
from .serializers import (
    ArticleListSerializer,
    ArticleSerializer,
    ArticleStatusSerializer,
    BookmarkSerializer,
    CategorySerializer,
    CommentModerationSerializer,
    CommentSerializer,
    ReviewSerializer,
    TagSerializer,
)

logger = logging.getLogger(__name__)


def is_editor(user):
    """Superusers, staff and Profile.role in (editor, admin) may publish."""
    if not user or not user.is_authenticated:
        return False
    if user.is_superuser or user.is_staff:
        return True
    profile = getattr(user, "profile", None)
    return bool(profile and profile.is_editor)


# ---------------------------------------------------------------------------
# Articles
# ---------------------------------------------------------------------------
class ArticleViewSet(viewsets.ModelViewSet):
    """Stories.

    Reads are public (published work only, unless the caller is an editor) and
    every write requires an editorial account — previously any anonymous request
    could create or delete articles.
    """

    queryset = Article.objects.all()
    permission_classes = [IsEditorOrReadOnly]
    filterset_class = ArticleFilter
    search_fields = ["headline", "body", "summary", "author__username", "tags__name"]
    ordering_fields = ["publishing_time", "view_count", "total_ratings", "headline", "updated_at"]
    ordering = ["-publishing_time"]
    parser_classes = [JSONParser, MultiPartParser, FormParser]

    def get_queryset(self):
        queryset = (
            Article.objects.with_stats()
            .select_related("author", "author__profile")
            .prefetch_related("categories", "tags", "reviews__user", "reviews__user__profile")
        )
        # Readers only ever see published stories; editors see everything.
        if self.action in {"list", "retrieve", "related", "views"}:
            queryset = queryset.visible_to(self.request.user)
        return queryset

    def get_serializer_class(self):
        if self.action == "list":
            return ArticleListSerializer
        if self.action == "status":
            return ArticleStatusSerializer
        return ArticleSerializer

    def get_permissions(self):
        if self.action in {"list", "retrieve", "related", "reviews", "search",
                           "trending", "increment_view"}:
            return [AllowAny()]
        # Saving a story is a reader action, not an editorial one.
        if self.action == "toggle_bookmark":
            return [IsAuthenticated()]
        return [IsAuthenticated(), IsEditorOrReadOnly()]

    # ------------------------------------------------------------------ list
    def list(self, request, *args, **kwargs):
        """Plain array by default; paged envelope when a page is requested."""
        queryset = self.filter_queryset(self.get_queryset())

        if not wants_pagination(request):
            data = self.get_serializer(queryset, many=True).data
            return Response(data)

        paginator = self.paginator
        page = paginator.paginate_queryset(queryset, request, view=self)
        if page is None:  # pragma: no cover
            return Response(self.get_serializer(queryset, many=True).data)
        return paginator.get_paginated_response(self.get_serializer(page, many=True).data)

    # -------------------------------------------------------------- lifecycle
    @action(detail=True, methods=["post"])
    def publish(self, request, pk=None):
        """Move a draft live (editors only)."""
        article = self.get_object()
        serializer = ArticleStatusSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        article.publish(when=timezone.now())
        logger.info("Article %s published by %s", article.pk, request.user)
        return Response(ArticleSerializer(article, context={"request": request}).data)

    @action(detail=True, methods=["post"])
    def archive(self, request, pk=None):
        article = self.get_object()
        article.archive()
        return Response(ArticleSerializer(article, context={"request": request}).data)

    @action(detail=True, methods=["post"], url_path="feature")
    def feature(self, request, pk=None):
        """Toggle (or explicitly set) the homepage hero flag."""
        article = self.get_object()
        serializer = ArticleStatusSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        requested = serializer.validated_data.get("is_featured")
        article.is_featured = (not article.is_featured) if requested is None else requested
        article.save(update_fields=["is_featured", "updated_at"])
        return Response({"id": article.id, "is_featured": article.is_featured})

    @action(detail=True, methods=["get", "post"], url_path="reviews")
    def reviews(self, request, pk=None):
        """Read or add reviews for one article."""
        article = self.get_object()

        if request.method == "GET":
            data = ReviewSerializer(
                article.reviews.select_related("user", "user__profile").all(),
                many=True,
                context={"request": request},
            ).data
            return Response(data)

        if not request.user.is_authenticated:
            raise PermissionDenied("Sign in to review this article.")
        if article.status != Article.Status.PUBLISHED and not is_editor(request.user):
            raise PermissionDenied("This story is not published yet.")

        # The story comes from the URL, so the caller only sends rating/comment.
        payload = dict(request.data)
        payload["article"] = article.pk
        serializer = ReviewSerializer(data=payload, context={"request": request})
        serializer.is_valid(raise_exception=True)
        review = serializer.save(article=article, user=request.user)
        # The model signal recalculates the totals; refresh so the caller sees them.
        article.refresh_from_db(fields=["total_ratings", "total_stars"])
        return Response(
            {
                "review": ReviewSerializer(review, context={"request": request}).data,
                "total_ratings": article.total_ratings,
                "average_rating": article.average_rating,
            },
            status=status.HTTP_201_CREATED,
        )

    @action(detail=True, methods=["get"])
    def related(self, request, pk=None):
        """Other published stories in the same sections."""
        article = self.get_object()
        categories = article.categories.all()
        queryset = (
            Article.objects.filter(categories__in=categories)
            .exclude(pk=article.pk)
            .filter(status=Article.Status.PUBLISHED)
            .select_related("author")
            .prefetch_related("categories", "tags")
            .order_by("-publishing_time")
            .distinct()[:6]
        )
        return Response(
            ArticleListSerializer(queryset, many=True, context={"request": request}).data
        )

    @action(detail=True, methods=["post"], permission_classes=[AllowAny], url_path="view")
    def increment_view(self, request, pk=None):
        """Count a read: a cheap counter plus a detail row."""
        article = self.get_object()
        article.register_view()

        forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
        ip = forwarded.split(",")[0].strip() if forwarded else request.META.get("REMOTE_ADDR")
        ArticleView.objects.create(
            article=article,
            user=request.user if request.user.is_authenticated else None,
            ip_address=ip if ip else None,
            user_agent=request.META.get("HTTP_USER_AGENT", "")[:250],
        )
        article.refresh_from_db(fields=["view_count"])
        return Response({"id": article.id, "view_count": article.view_count})

    @action(detail=True, methods=["get"])
    def views(self, request, pk=None):
        """Read report for one story (editors only)."""
        if not is_editor(request.user):
            raise PermissionDenied("Only editors can read the view report.")
        article = self.get_object()
        return Response(
            {
                "article": article.id,
                "view_count": article.view_count,
                "recent": list(article.views.values("viewed_at", "user_id")[:50]),
            }
        )

    # -------------------------------------------------------------- bookmarks
    @action(detail=True, methods=["post"], permission_classes=[IsAuthenticated], url_path="bookmark")
    def toggle_bookmark(self, request, pk=None):
        """Save or unsave a story for the signed-in reader."""
        article = self.get_object()
        existing = Bookmark.objects.filter(user=request.user, article=article).first()
        if existing:
            existing.delete()
            return Response({"bookmarked": False, "id": article.id})
        Bookmark.objects.create(user=request.user, article=article)
        return Response({"bookmarked": True, "id": article.id}, status=status.HTTP_201_CREATED)

    # ------------------------------------------------------------------ search
    @action(detail=False, methods=["get"])
    def search(self, request):
        """GET /article/list/search/?q=... — headline and body search."""
        term = (request.query_params.get("q") or "").strip()
        queryset = (
            Article.objects.published()
            .select_related("author")
            .prefetch_related("categories", "tags")
        )
        if term:
            queryset = queryset.filter(
                Q(headline__icontains=term)
                | Q(body__icontains=term)
                | Q(summary__icontains=term)
            )
        results = queryset.order_by("-publishing_time")[:40]
        return Response(
            {
                "query": term,
                "count": len(results),
                "results": ArticleListSerializer(
                    results, many=True, context={"request": request}
                ).data,
            }
        )

    @action(detail=False, methods=["get"])
    def trending(self, request):
        """Most-read published stories."""
        queryset = (
            Article.objects.published()
            .order_by("-view_count", "-publishing_time")
            .select_related("author")[:10]
        )
        return Response(
            ArticleListSerializer(queryset, many=True, context={"request": request}).data
        )


# ---------------------------------------------------------------------------
# Sections and tags
# ---------------------------------------------------------------------------
class CategoryViewSet(viewsets.ModelViewSet):
    """Sections. Public to read, editorial to change."""

    queryset = Category.objects.all()
    serializer_class = CategorySerializer
    permission_classes = [IsEditorOrReadOnly]
    pagination_class = None
    search_fields = ["name", "description"]
    ordering_fields = ["order", "name"]
    ordering = ["order", "name"]

    def get_queryset(self):
        queryset = Category.objects.all()
        if self.action == "list":
            queryset = queryset.annotate(
                article_count=Count("articles", distinct=True),
                published_count=Count(
                    "articles",
                    filter=Q(articles__status=Article.Status.PUBLISHED),
                    distinct=True,
                ),
            )
            if not is_editor(self.request.user):
                queryset = queryset.filter(is_active=True)
        return queryset


class TagViewSet(viewsets.ModelViewSet):
    """Tags are created implicitly when an article is saved with new ones."""

    queryset = Tag.objects.all()
    serializer_class = TagSerializer
    permission_classes = [IsEditorOrReadOnly]
    pagination_class = None
    search_fields = ["name"]
    ordering = ["name"]

    def get_queryset(self):
        queryset = Tag.objects.all()
        if self.action == "list":
            queryset = queryset.annotate(article_count=Count("articles", distinct=True))
        return queryset


# ---------------------------------------------------------------------------
# Reviews
# ---------------------------------------------------------------------------
class ReviewViewSet(viewsets.ModelViewSet):
    """Reviews. Anyone may read; only the author (or an editor) may change one."""

    queryset = Review.objects.select_related("user", "user__profile", "article").all()
    serializer_class = ReviewSerializer
    filterset_fields = ["article", "user", "rating"]
    ordering = ["-created_at"]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "review"

    def get_permissions(self):
        # SAFE_METHODS holds HTTP verbs, so test the request method — not
        # `self.action`, which is the action *name* ("list", "retrieve", ...).
        if self.request.method in SAFE_METHODS:
            return [AllowAny()]
        return [IsAuthenticated(), IsOwnerOrEditor()]

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)


# ---------------------------------------------------------------------------
# Comments
# ---------------------------------------------------------------------------
class CommentViewSet(viewsets.ModelViewSet):
    """Comments with a moderation queue."""

    queryset = Comment.objects.select_related("user", "user__profile", "article").all()
    serializer_class = CommentSerializer
    filterset_class = CommentFilter
    pagination_class = None
    ordering_fields = ["created_at"]
    ordering = ["created_at"]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "comment"

    def get_permissions(self):
        if self.action in {"approve", "reject", "queue"}:
            return [IsAuthenticated()]
        # SAFE_METHODS holds HTTP verbs; `self.action` is the action name.
        if self.request.method in SAFE_METHODS:
            return [AllowAny()]
        return [IsAuthenticated(), IsOwnerOrEditor()]

    def get_queryset(self):
        """Readers see approved top-level comments; editors see everything."""
        if self.action in {"update", "partial_update", "destroy"}:
            return Comment.objects.filter(user=self.request.user)
        queryset = super().get_queryset().filter(parent__isnull=True)
        if is_editor(self.request.user):
            return queryset
        return queryset.filter(is_approved=True)

    def get_object(self):
        """Moderation targets any comment, approved or not.

        `get_queryset()` deliberately hides pending comments from readers, so
        the editor-only actions bypass it — otherwise a moderator could never
        approve the very comment they are looking at (404).
        """
        if self.action in {"approve", "reject"}:
            from django.shortcuts import get_object_or_404

            lookup_url_kwarg = self.lookup_url_kwarg or self.lookup_field
            obj = get_object_or_404(
                Comment.objects.select_related("user", "article"),
                **{self.lookup_field: self.kwargs[lookup_url_kwarg]},
            )
            self.check_object_permissions(self.request, obj)
            return obj
        return super().get_object()

    def perform_create(self, serializer):
        article = serializer.validated_data.get("article")
        if article is not None and not article.allow_comments:
            raise ValidationError({"article": "Comments are closed on this story."})
        # Staff comments appear immediately; readers wait for a moderator.
        auto_approve = is_editor(self.request.user)
        serializer.save(
            user=self.request.user,
            is_approved=auto_approve,
            moderated_by=self.request.user if auto_approve else None,
            moderated_at=timezone.now() if auto_approve else None,
        )

    def perform_update(self, serializer):
        serializer.save(is_edited=True)

    @action(detail=True, methods=["post"], url_path="approve")
    def approve(self, request, pk=None):
        """Publish a pending comment (editors only)."""
        if not is_editor(request.user):
            raise PermissionDenied("Only editors can moderate comments.")
        comment = self.get_object()
        payload = CommentModerationSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        comment.approve(request.user, payload.validated_data.get("note", ""))
        return Response(CommentSerializer(comment, context={"request": request}).data)

    @action(detail=True, methods=["post"], url_path="reject")
    def reject(self, request, pk=None):
        """Hide a comment (editors only)."""
        if not is_editor(request.user):
            raise PermissionDenied("Only editors can moderate comments.")
        comment = self.get_object()
        payload = CommentModerationSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        comment.reject(request.user, payload.validated_data.get("note", ""))
        return Response(CommentSerializer(comment, context={"request": request}).data)

    @action(detail=False, methods=["get"], url_path="queue")
    def queue(self, request):
        """Comments waiting for a decision (editors only)."""
        if not is_editor(request.user):
            raise PermissionDenied("Only editors can read the moderation queue.")
        pending = Comment.objects.filter(is_approved=False).select_related("user", "article")
        return Response(
            {
                "count": pending.count(),
                "results": CommentSerializer(
                    pending[:100], many=True, context={"request": request}
                ).data,
            }
        )

    @action(detail=False, methods=["get"], url_path="mine")
    def mine(self, request):
        if not request.user.is_authenticated:
            raise PermissionDenied("Sign in first.")
        own = Comment.objects.filter(user=request.user).select_related("article")
        return Response(CommentSerializer(own, many=True, context={"request": request}).data)


# ---------------------------------------------------------------------------
# Bookmarks
# ---------------------------------------------------------------------------
class BookmarkViewSet(viewsets.ModelViewSet):
    """A reader's saved stories. Always scoped to the caller."""

    serializer_class = BookmarkSerializer
    permission_classes = [IsAuthenticated]
    filterset_fields = ["article"]
    pagination_class = None
    ordering = ["-created_at"]

    def get_queryset(self):
        return (
            Bookmark.objects.filter(user=self.request.user)
            .select_related("article")
            .prefetch_related("article__categories")
        )

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)

    @action(detail=False, methods=["get"], url_path=r"check/(?P<article_id>[0-9]+)")
    def check(self, request, article_id=None):
        """GET /article/bookmarks/check/<id>/ — is this story saved?"""
        exists = Bookmark.objects.filter(user=request.user, article_id=article_id).exists()
        return Response({"article": int(article_id), "bookmarked": exists})


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------
class StatsView(viewsets.ViewSet):
    """Editorial overview for the newsroom home."""

    permission_classes = [IsAuthenticated]

    def list(self, request):
        if not is_editor(request.user):
            raise PermissionDenied("Only editors can read the dashboard.")
        articles = Article.objects.all()
        return Response(
            {
                "articles": {
                    "total": articles.count(),
                    "published": articles.filter(status=Article.Status.PUBLISHED).count(),
                    "drafts": articles.filter(status=Article.Status.DRAFT).count(),
                    "archived": articles.filter(status=Article.Status.ARCHIVED).count(),
                    "featured": articles.filter(is_featured=True).count(),
                },
                "engagement": {
                    "total_view_events": ArticleView.objects.count(),
                    "reviews": Review.objects.count(),
                    "comments": Comment.objects.count(),
                    "pending_comments": Comment.objects.filter(is_approved=False).count(),
                    "bookmarks": Bookmark.objects.count(),
                },
                "top_stories": list(
                    articles.filter(status=Article.Status.PUBLISHED)
                    .order_by("-view_count")
                    .values("id", "headline", "view_count")[:10]
                ),
            }
        )
