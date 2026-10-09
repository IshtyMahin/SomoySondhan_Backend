"""Filtering for the newsroom API.

`?category=politics` keeps working exactly as before (matched on the category
slug), and the rest are additive.
"""

from django.db.models import Q
from django_filters import rest_framework as filters

from .models import Article, Comment


class ArticleFilter(filters.FilterSet):
    # The original endpoint filtered by `category` as a slug.
    category = filters.CharFilter(method="filter_category")
    categories = filters.CharFilter(method="filter_category")
    tag = filters.CharFilter(method="filter_tag")
    tags = filters.CharFilter(method="filter_tag")
    author = filters.NumberFilter(field_name="author_id")
    status = filters.CharFilter(field_name="status")
    featured = filters.BooleanFilter(field_name="is_featured")
    published_after = filters.IsoDateTimeFilter(field_name="publishing_time", lookup_expr="gte")
    published_before = filters.IsoDateTimeFilter(field_name="publishing_time", lookup_expr="lte")
    min_rating = filters.NumberFilter(method="filter_min_rating")
    has_image = filters.BooleanFilter(method="filter_has_image")

    class Meta:
        model = Article
        fields = ["category", "categories", "tag", "tags", "author", "status", "featured"]

    def _split(self, value):
        return [part.strip() for part in str(value).split(",") if part.strip()]

    def filter_category(self, queryset, name, value):
        names = self._split(value)
        if not names:
            return queryset
        # Match either the slug or the display name, so ?category=Politics and
        # ?category=politics both work.
        query = Q()
        for item in names:
            query |= Q(categories__slug__iexact=item) | Q(categories__name__iexact=item)
        return queryset.filter(query).distinct()

    def filter_tag(self, queryset, name, value):
        names = self._split(value)
        if not names:
            return queryset
        query = Q()
        for item in names:
            query |= Q(tags__slug__iexact=item) | Q(tags__name__iexact=item)
        return queryset.filter(query).distinct()

    def filter_min_rating(self, queryset, name, value):
        """Average rating is denormalised, so compare the ratio."""
        from django.db.models import F, Q as QExpr

        return queryset.filter(
            QExpr(total_ratings__gt=0)
            & QExpr(total_stars__gte=F("total_ratings") * float(value))
        )

    def filter_has_image(self, queryset, name, value):
        if value:
            return queryset.exclude(Q(cover_image="") | Q(cover_image__isnull=True))
        return queryset.filter(Q(cover_image="") | Q(cover_image__isnull=True))


class CommentFilter(filters.FilterSet):
    article = filters.NumberFilter(field_name="article_id")
    user = filters.NumberFilter(field_name="user_id")
    approved = filters.BooleanFilter(field_name="is_approved")

    class Meta:
        model = Comment
        fields = ["article", "user", "approved"]
