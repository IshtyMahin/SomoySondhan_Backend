"""Newsroom models: categories, tags, articles, reviews, comments and bookmarks.

The original `Article`, `Category` and `Review` tables already hold live data, so
they are extended in place — no field is removed or renamed and no column is made
required, which keeps every existing row valid.
"""

from django.conf import settings
from django.db import models
from django.db.models import Count, Q, Sum
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver
from django.utils import timezone
from django.utils.text import slugify


# ---------------------------------------------------------------------------
# Taxonomy
# ---------------------------------------------------------------------------
class Category(models.Model):
    """A section of the paper (Politics, Sports, ...)."""

    name = models.CharField(max_length=200)
    slug = models.SlugField(max_length=100, unique=True, null=True, blank=True)
    description = models.TextField(max_length=300, blank=True, default="")
    order = models.PositiveSmallIntegerField(
        default=0, help_text="Lower numbers appear first in the navigation."
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True, null=True)

    class Meta:
        ordering = ["order", "name"]
        verbose_name_plural = "categories"

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name

    @property
    def published_count(self):
        # `CategoryViewSet` annotates the list queryset with a `published_count`
        # of the same name; Django populates annotations via setattr, so the
        # property needs a setter to accept it. Falls back to a live count.
        value = getattr(self, "_published_count", None)
        if value is not None:
            return value
        return self.articles.filter(status=Article.Status.PUBLISHED).count()

    @published_count.setter
    def published_count(self, value):
        self._published_count = value


class Tag(models.Model):
    """A free-form label; an article can carry many."""

    name = models.CharField(max_length=60, unique=True)
    slug = models.SlugField(max_length=80, unique=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name


# ---------------------------------------------------------------------------
# Articles
# ---------------------------------------------------------------------------
class ArticleQuerySet(models.QuerySet):
    def published(self):
        return self.filter(status=Article.Status.PUBLISHED)

    def drafts(self):
        return self.filter(status=Article.Status.DRAFT)

    def visible_to(self, user):
        """Readers see published work; editors also see drafts."""
        profile = getattr(user, "profile", None)
        if user and user.is_authenticated and (
            user.is_superuser or user.is_staff or (profile and profile.is_editor)
        ):
            return self
        return self.published()

    def with_stats(self):
        return self.annotate(
            reviews_count=Count("reviews", distinct=True),
            comments_count=Count(
                "comments", filter=Q(comments__is_approved=True), distinct=True
            ),
            bookmarks_count=Count("bookmarks", distinct=True),
        )


class Article(models.Model):
    """A story.

    Existing rows keep working: `headline`, `body`, `publishing_time`,
    `total_ratings` and `total_stars` are untouched, and every new column has a
    default or is nullable.
    """

    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        PUBLISHED = "published", "Published"
        ARCHIVED = "archived", "Archived"

    headline = models.CharField(max_length=1000)
    body = models.TextField()
    summary = models.CharField(
        max_length=500,
        blank=True,
        default="",
        help_text="Standfirst shown on cards and in search results.",
    )

    categories = models.ManyToManyField(Category, related_name="articles", default="Latest")
    tags = models.ManyToManyField(Tag, related_name="articles", blank=True)

    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="articles",
        help_text="Left empty for stories imported before accounts were tracked.",
    )
    cover_image = models.ImageField(upload_to="articles/covers/", blank=True, null=True)
    cover_caption = models.CharField(max_length=250, blank=True, default="")

    status = models.CharField(max_length=12, choices=Status.choices, default=Status.PUBLISHED)
    is_featured = models.BooleanField(default=False, help_text="Promote to the homepage hero.")
    allow_comments = models.BooleanField(default=True)

    # `auto_now_add=True` matches the existing column, so publishing_time never
    # changes on edit. `publish()` sets it explicitly for stories going live.
    publishing_time = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True, null=True)

    # Denormalised rating totals — kept in sync by the Review signals below.
    total_ratings = models.IntegerField(default=0)
    total_stars = models.IntegerField(default=0)

    view_count = models.PositiveIntegerField(default=0)

    objects = ArticleQuerySet.as_manager()

    class Meta:
        ordering = ["-publishing_time"]
        indexes = [
            models.Index(fields=["-publishing_time"]),
            models.Index(fields=["status", "-publishing_time"]),
            models.Index(fields=["-view_count"]),
        ]

    def __str__(self):
        return self.headline[:70]

    # ------------------------------------------------------------------ helpers
    @property
    def average_rating(self):
        if self.total_ratings:
            return self.total_stars / self.total_ratings
        return 0

    @property
    def is_published(self):
        return self.status == self.Status.PUBLISHED

    @property
    def reading_minutes(self):
        words = len((self.body or "").split())
        return max(1, round(words / 200))

    # Counts are exposed as properties that prefer the value `with_stats()`
    # annotated onto the queryset, so a list of articles costs three queries
    # instead of three per article. `with_stats()` annotates using these same
    # names, and Django populates annotations with setattr — so each property
    # needs a setter that stashes the annotated value in a private slot. When
    # the value was not annotated, the getter falls back to a live count.
    @property
    def reviews_count(self):
        value = getattr(self, "_reviews_count", None)
        return value if value is not None else self.reviews.count()

    @reviews_count.setter
    def reviews_count(self, value):
        self._reviews_count = value

    @property
    def comments_count(self):
        value = getattr(self, "_comments_count", None)
        return value if value is not None else self.comments.filter(is_approved=True).count()

    @comments_count.setter
    def comments_count(self, value):
        self._comments_count = value

    @property
    def bookmarks_count(self):
        value = getattr(self, "_bookmarks_count", None)
        return value if value is not None else self.bookmarks.count()

    @bookmarks_count.setter
    def bookmarks_count(self, value):
        self._bookmarks_count = value

    def publish(self, when=None):
        """Move a draft live."""
        self.status = self.Status.PUBLISHED
        self.save(update_fields=["status", "updated_at"])
        if when:
            # auto_now_add ignores assignment, so update the column directly.
            Article.objects.filter(pk=self.pk).update(publishing_time=when)
            self.refresh_from_db(fields=["publishing_time"])
        return self

    def archive(self):
        self.status = self.Status.ARCHIVED
        self.save(update_fields=["status", "updated_at"])
        return self

    def register_view(self):
        """Count a read without racing other readers."""
        Article.objects.filter(pk=self.pk).update(view_count=models.F("view_count") + 1)

    def recalculate_rating(self):
        """Recompute the cached totals from the reviews actually present."""
        totals = self.reviews.aggregate(total=Count("id"), stars=Sum("rating"))
        self.total_ratings = totals["total"] or 0
        self.total_stars = totals["stars"] or 0
        self.save(update_fields=["total_ratings", "total_stars"])


class Review(models.Model):
    """A star rating with a written comment. One per reader per article."""

    RATING_CHOICES = (
        (1, "1 star"),
        (2, "2 stars"),
        (3, "3 stars"),
        (4, "4 stars"),
    )

    article = models.ForeignKey(Article, related_name="reviews", on_delete=models.CASCADE)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    rating = models.IntegerField(choices=RATING_CHOICES)
    comment = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True, null=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["article", "user"], name="one_review_per_reader_per_article"
            ),
        ]

    def __str__(self):
        return "review on {0} — {1} stars".format(self.article_id, self.rating)


@receiver(post_save, sender=Review)
@receiver(post_delete, sender=Review)
def update_article_rating(sender, instance, **kwargs):
    """Keep Article.total_ratings/total_stars in step with its reviews.

    The original signal only listened to post_save, so deleting a review left the
    article's average permanently wrong.
    """
    try:
        article = Article.objects.get(pk=instance.article_id)
    except Article.DoesNotExist:
        return
    article.recalculate_rating()


# ---------------------------------------------------------------------------
# Reader engagement
# ---------------------------------------------------------------------------
class Comment(models.Model):
    """A reader comment, moderated before it appears."""

    article = models.ForeignKey(Article, related_name="comments", on_delete=models.CASCADE)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="comments"
    )
    body = models.TextField(max_length=2000)
    parent = models.ForeignKey(
        "self", null=True, blank=True, related_name="replies", on_delete=models.CASCADE
    )

    is_approved = models.BooleanField(default=False)
    is_edited = models.BooleanField(default=False)
    moderated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        related_name="moderated_comments",
        on_delete=models.SET_NULL,
    )
    moderated_at = models.DateTimeField(null=True, blank=True)
    moderation_note = models.CharField(max_length=250, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["created_at"]
        indexes = [
            models.Index(fields=["article", "is_approved"]),
            models.Index(fields=["is_approved", "-created_at"]),
        ]

    def __str__(self):
        return "Comment #{0} on article {1}".format(self.pk, self.article_id)

    def approve(self, moderator, note=""):
        self.is_approved = True
        self.moderated_by = moderator
        self.moderated_at = timezone.now()
        self.moderation_note = note
        self.save(update_fields=["is_approved", "moderated_by", "moderated_at", "moderation_note"])
        return self

    def reject(self, moderator, note=""):
        self.is_approved = False
        self.moderated_by = moderator
        self.moderated_at = timezone.now()
        self.moderation_note = note
        self.save(update_fields=["is_approved", "moderated_by", "moderated_at", "moderation_note"])
        return self


class Bookmark(models.Model):
    """A reader saving a story for later."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, related_name="bookmarks", on_delete=models.CASCADE
    )
    article = models.ForeignKey(Article, related_name="bookmarks", on_delete=models.CASCADE)
    note = models.CharField(max_length=250, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["user", "article"], name="one_bookmark_per_reader_per_article"
            ),
        ]

    def __str__(self):
        return "bookmark by user {0} on article {1}".format(self.user_id, self.article_id)


class ArticleView(models.Model):
    """One row per read, for a simple "most read" report.

    `Article.view_count` is the cheap counter used in lists; this table keeps the
    detail (who and when) without slowing those queries down.
    """

    article = models.ForeignKey(Article, related_name="views", on_delete=models.CASCADE)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        related_name="article_views",
        on_delete=models.SET_NULL,
    )
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=250, blank=True)
    viewed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-viewed_at"]
        indexes = [models.Index(fields=["article", "-viewed_at"])]

    def __str__(self):
        return "view of article {0}".format(self.article_id)
