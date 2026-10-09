"""Serializers for the newsroom API.

The response shape stays compatible with the existing frontend, which reads
`id, headline, body, categories, publishing_time, reviews, total_ratings,
average_rating, star_counts` — plus the new `status`, `tags`, `cover_image_url`,
`view_count` and engagement counters.
"""

from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils.text import slugify
from rest_framework import serializers

from .models import Article, ArticleView, Bookmark, Category, Comment, Review, Tag

User = get_user_model()


# ---------------------------------------------------------------------------
# Taxonomy
# ---------------------------------------------------------------------------
class CategorySerializer(serializers.ModelSerializer):
    """Frontend contract: `{id, name}` — the extra fields are additive."""

    article_count = serializers.SerializerMethodField()
    published_count = serializers.SerializerMethodField()

    class Meta:
        model = Category
        fields = ["id", "name", "slug", "description", "order", "is_active",
                  "article_count", "published_count"]
        read_only_fields = ["slug"]
        extra_kwargs = {"name": {"required": True, "allow_blank": False}}

    def get_article_count(self, obj):
        return getattr(obj, "article_count", None) or obj.articles.count()

    def get_published_count(self, obj):
        return getattr(obj, "published_count", None) or obj.published_count


class TagSerializer(serializers.ModelSerializer):
    article_count = serializers.SerializerMethodField()

    class Meta:
        model = Tag
        fields = ["id", "name", "slug", "article_count"]
        read_only_fields = ["slug"]

    def get_article_count(self, obj):
        return getattr(obj, "article_count", None) or obj.articles.count()


class TagRelatedField(serializers.RelatedField):
    """Accept plain strings or ids for tags: `["climate", "politics"]`."""

    def to_representation(self, value):
        return value.name

    def to_internal_value(self, data):
        if isinstance(data, int) or (isinstance(data, str) and data.isdigit()):
            try:
                return Tag.objects.get(pk=int(data))
            except Tag.DoesNotExist:
                raise serializers.ValidationError("No tag with id {0}.".format(data))
        name = str(data).strip()
        if not name:
            raise serializers.ValidationError("A tag name cannot be empty.")
        tag, _ = Tag.objects.get_or_create(name=name, defaults={"slug": slugify(name)})
        return tag


# ---------------------------------------------------------------------------
# Reviews
# ---------------------------------------------------------------------------
class ReviewSerializer(serializers.ModelSerializer):
    """`user` defaults to the caller, so the existing frontend payload works."""

    user = serializers.PrimaryKeyRelatedField(
        queryset=User.objects.all(), required=False, default=serializers.CurrentUserDefault()
    )
    username = serializers.CharField(source="user.username", read_only=True)
    display_name = serializers.SerializerMethodField()
    avatar = serializers.SerializerMethodField()

    class Meta:
        model = Review
        fields = ["id", "article", "user", "username", "display_name", "avatar",
                  "rating", "comment", "created_at", "updated_at"]
        read_only_fields = ["created_at", "updated_at"]

    def get_display_name(self, obj):
        profile = getattr(obj.user, "profile", None)
        return profile.display_name if profile else obj.user.username

    def get_avatar(self, obj):
        profile = getattr(obj.user, "profile", None)
        if profile and profile.avatar:
            request = self.context.get("request")
            url = profile.avatar.url
            return request.build_absolute_uri(url) if request else url
        return None

    def validate_rating(self, value):
        if value not in dict(Review.RATING_CHOICES):
            raise serializers.ValidationError("Choose a rating from 1 to 4.")
        return value

    def validate_comment(self, value):
        text = (value or "").strip()
        if len(text) < 3:
            raise serializers.ValidationError("Please write at least a few words.")
        return text

    def validate(self, attrs):
        article = attrs.get("article") or getattr(self.instance, "article", None)
        user = attrs.get("user") or getattr(self.instance, "user", None)
        if article and user:
            existing = Review.objects.filter(article=article, user=user)
            if self.instance:
                existing = existing.exclude(pk=self.instance.pk)
            if existing.exists():
                raise serializers.ValidationError(
                    {"detail": "You have already reviewed this article."}
                )
        return attrs


# ---------------------------------------------------------------------------
# Comments
# ---------------------------------------------------------------------------
class CommentSerializer(serializers.ModelSerializer):
    user = serializers.PrimaryKeyRelatedField(read_only=True)
    username = serializers.CharField(source="user.username", read_only=True)
    display_name = serializers.SerializerMethodField()
    replies = serializers.SerializerMethodField()

    class Meta:
        model = Comment
        fields = ["id", "article", "user", "username", "display_name", "body", "parent",
                  "is_approved", "is_edited", "moderation_note",
                  "created_at", "updated_at", "replies"]
        read_only_fields = ["is_approved", "is_edited", "moderation_note",
                            "created_at", "updated_at"]

    def get_display_name(self, obj):
        profile = getattr(obj.user, "profile", None)
        return profile.display_name if profile else obj.user.username

    def get_replies(self, obj):
        # One level of nesting: deeper threads are flattened so a long argument
        # cannot blow up the payload.
        children = [reply for reply in obj.replies.all() if reply.is_approved]
        return CommentSerializer(children, many=True, context=self.context).data

    def validate_body(self, value):
        text = (value or "").strip()
        if len(text) < 2:
            raise serializers.ValidationError("Write something first.")
        if len(text) > 2000:
            raise serializers.ValidationError("Comments are limited to 2000 characters.")
        return text

    def validate_parent(self, value):
        article = self.initial_data.get("article") or getattr(self.instance, "article_id", None)
        if value is not None and article is not None and str(value.article_id) != str(article):
            raise serializers.ValidationError("A reply must belong to the same article.")
        return value


class CommentModerationSerializer(serializers.Serializer):
    """Payload for approve / reject."""

    note = serializers.CharField(required=False, allow_blank=True, max_length=250)


# ---------------------------------------------------------------------------
# Bookmarks
# ---------------------------------------------------------------------------
class BookmarkSerializer(serializers.ModelSerializer):
    user = serializers.PrimaryKeyRelatedField(read_only=True)
    headline = serializers.CharField(source="article.headline", read_only=True)
    article_detail = serializers.SerializerMethodField()

    class Meta:
        model = Bookmark
        fields = ["id", "user", "article", "headline", "note", "created_at", "article_detail"]
        read_only_fields = ["created_at"]

    def get_article_detail(self, obj):
        article = obj.article
        cover = None
        if article.cover_image:
            request = self.context.get("request")
            cover = request.build_absolute_uri(article.cover_image.url) if request else article.cover_image.url
        return {
            "id": article.id,
            "headline": article.headline,
            "summary": article.summary,
            "categories": [category.name for category in article.categories.all()],
            "publishing_time": article.publishing_time,
            "cover_image": cover,
            "reading_minutes": article.reading_minutes,
            "average_rating": round(article.average_rating, 2),
        }

    def validate(self, attrs):
        user = self.context["request"].user
        article = attrs.get("article")
        if article and Bookmark.objects.filter(user=user, article=article).exists():
            raise serializers.ValidationError({"detail": "You have already saved this article."})
        return attrs


# ---------------------------------------------------------------------------
# Articles
# ---------------------------------------------------------------------------
class ArticleListSerializer(serializers.ModelSerializer):
    """Compact card shape for feeds and search results."""

    categories = serializers.SlugRelatedField(many=True, read_only=True, slug_field="name")
    tags = serializers.SlugRelatedField(many=True, read_only=True, slug_field="name")
    average_rating = serializers.FloatField(read_only=True)
    author_name = serializers.SerializerMethodField()
    cover_image_url = serializers.SerializerMethodField()
    reading_minutes = serializers.IntegerField(read_only=True)
    comments_count = serializers.SerializerMethodField()

    class Meta:
        model = Article
        fields = ["id", "headline", "summary", "body", "categories", "tags", "status",
                  "publishing_time", "updated_at", "total_ratings", "average_rating",
                  "view_count", "is_featured", "cover_image_url", "author_name",
                  "reading_minutes", "comments_count"]

    def get_author_name(self, obj):
        if not obj.author:
            return "Somoy Sondhan Desk"
        profile = getattr(obj.author, "profile", None)
        return profile.display_name if profile else obj.author.username

    def get_cover_image_url(self, obj):
        if not obj.cover_image:
            return None
        request = self.context.get("request")
        return request.build_absolute_uri(obj.cover_image.url) if request else obj.cover_image.url

    def get_comments_count(self, obj):
        # Prefers the annotation from `Article.objects.with_stats()`, then the
        # model property, so a feed costs one query instead of one per card.
        annotated = getattr(obj, "comments_count", None)
        if annotated is not None:
            return annotated
        return obj.comments_count


class ArticleSerializer(serializers.ModelSerializer):
    """Full article, including the rating breakdown the frontend renders."""

    categories = serializers.SlugRelatedField(
        many=True, slug_field="name", queryset=Category.objects.all()
    )
    tags = TagRelatedField(many=True, required=False, queryset=Tag.objects.all())
    reviews = ReviewSerializer(many=True, read_only=True)
    author = serializers.PrimaryKeyRelatedField(read_only=True)
    author_name = serializers.SerializerMethodField()

    average_rating = serializers.FloatField(read_only=True)
    total_ratings = serializers.IntegerField(read_only=True)
    star_counts = serializers.SerializerMethodField()
    reading_minutes = serializers.IntegerField(read_only=True)
    comments_count = serializers.SerializerMethodField()
    bookmarks_count = serializers.SerializerMethodField()
    is_bookmarked = serializers.SerializerMethodField()
    cover_image_url = serializers.SerializerMethodField()

    class Meta:
        model = Article
        fields = ["id", "headline", "body", "summary", "categories", "tags",
                  "author", "author_name", "cover_image", "cover_image_url", "cover_caption",
                  "status", "is_featured", "allow_comments",
                  "publishing_time", "updated_at",
                  "reviews", "total_ratings", "average_rating", "star_counts",
                  "view_count", "reading_minutes", "comments_count",
                  "bookmarks_count", "is_bookmarked"]
        read_only_fields = ["view_count", "publishing_time", "updated_at"]
        extra_kwargs = {
            "cover_image": {"required": False, "allow_null": True},
            "summary": {"required": False},
        }

    # -------------------------------------------------------------- computed
    def get_author_name(self, obj):
        if not obj.author:
            return "Somoy Sondhan Desk"
        profile = getattr(obj.author, "profile", None)
        return profile.display_name if profile else obj.author.username

    def get_star_counts(self, obj):
        """`{"1": n, "2": n, "3": n, "4": n}` — string keys, as JSON objects use."""
        counts = {"1": 0, "2": 0, "3": 0, "4": 0}
        for review in obj.reviews.all():
            key = str(review.rating)
            if key in counts:
                counts[key] += 1
        return counts

    def get_comments_count(self, obj):
        return obj.comments_count

    def get_bookmarks_count(self, obj):
        return obj.bookmarks_count

    def get_is_bookmarked(self, obj):
        request = self.context.get("request")
        if not request or not request.user.is_authenticated:
            return False
        return obj.bookmarks.filter(user=request.user).exists()

    def get_cover_image_url(self, obj):
        if not obj.cover_image:
            return None
        request = self.context.get("request")
        return request.build_absolute_uri(obj.cover_image.url) if request else obj.cover_image.url

    # -------------------------------------------------------------- validation
    def validate_headline(self, value):
        text = (value or "").strip()
        if len(text) < 5:
            raise serializers.ValidationError("A headline needs at least 5 characters.")
        return text

    def validate_body(self, value):
        text = (value or "").strip()
        if len(text) < 20:
            raise serializers.ValidationError("An article body needs at least 20 characters.")
        return text

    def validate_categories(self, value):
        if not value:
            raise serializers.ValidationError("Choose at least one section.")
        return value

    # ------------------------------------------------------------------ write
    @transaction.atomic
    def create(self, validated_data):
        tags = validated_data.pop("tags", [])
        categories = validated_data.pop("categories", [])
        request = self.context.get("request")
        if request and request.user.is_authenticated:
            validated_data.setdefault("author", request.user)

        article = Article.objects.create(**validated_data)
        article.categories.set(categories)
        if tags:
            article.tags.set(tags)
        return article

    @transaction.atomic
    def update(self, instance, validated_data):
        tags = validated_data.pop("tags", None)
        categories = validated_data.pop("categories", None)

        for field, value in validated_data.items():
            setattr(instance, field, value)
        instance.save()

        if categories is not None:
            instance.categories.set(categories)
        if tags is not None:
            instance.tags.set(tags)
        return instance


class ArticleStatusSerializer(serializers.Serializer):
    """Body for the publish / archive / feature actions."""

    status = serializers.ChoiceField(choices=Article.Status.choices, required=False)
    is_featured = serializers.BooleanField(required=False)
    note = serializers.CharField(required=False, allow_blank=True, max_length=250)


class ArticleViewSerializer(serializers.ModelSerializer):
    class Meta:
        model = ArticleView
        fields = ["id", "article", "user", "viewed_at"]
        read_only_fields = fields
