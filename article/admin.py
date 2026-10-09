"""Admin for the newsroom — usable for real editorial work."""

from django.contrib import admin
from django.utils.html import format_html

from .models import Article, ArticleView, Bookmark, Category, Comment, Review, Tag


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "slug", "order", "is_active", "article_total")
    list_editable = ("order", "is_active")
    search_fields = ("name", "description")
    prepopulated_fields = {"slug": ("name",)}

    @admin.display(description="articles")
    def article_total(self, obj):
        return obj.articles.count()


@admin.register(Tag)
class TagAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "slug", "article_total")
    search_fields = ("name",)
    prepopulated_fields = {"slug": ("name",)}

    @admin.display(description="articles")
    def article_total(self, obj):
        return obj.articles.count()


class ReviewInline(admin.TabularInline):
    model = Review
    extra = 0
    readonly_fields = ("user", "rating", "comment", "created_at")
    can_delete = True


class CommentInline(admin.TabularInline):
    model = Comment
    extra = 0
    fields = ("user", "body", "is_approved", "created_at")
    readonly_fields = ("user", "created_at")


@admin.register(Article)
class ArticleAdmin(admin.ModelAdmin):
    list_display = ("id", "headline_short", "status", "is_featured", "author",
                    "section_list", "view_count", "published_at")
    list_filter = ("status", "is_featured", "allow_comments", "categories", "tags")
    search_fields = ("headline", "body", "summary")
    date_hierarchy = "publishing_time"
    ordering = ("-publishing_time",)
    inlines = [ReviewInline, CommentInline]
    filter_horizontal = ("categories", "tags")
    readonly_fields = ("total_ratings", "total_stars", "view_count", "updated_at", "cover_preview")
    list_editable = ("status", "is_featured")
    actions = ["make_published", "make_draft", "make_archived", "feature", "unfeature"]
    fieldsets = (
        (None, {"fields": ("headline", "summary", "body")}),
        ("Placement", {"fields": ("categories", "tags", "status", "is_featured", "allow_comments")}),
        ("Media", {"fields": ("cover_image", "cover_preview", "cover_caption")}),
        ("Byline", {"fields": ("author",)}),
        ("Statistics", {"fields": ("total_ratings", "total_stars", "view_count", "publishing_time", "updated_at")}),
    )

    @admin.display(description="headline")
    def headline_short(self, obj):
        return obj.headline[:70]

    @admin.display(description="sections")
    def section_list(self, obj):
        return ", ".join(category.name for category in obj.categories.all()) or "—"

    @admin.display(description="published")
    def published_at(self, obj):
        return obj.publishing_time.strftime("%Y-%m-%d %H:%M") if obj.publishing_time else "—"

    @admin.display(description="cover")
    def cover_preview(self, obj):
        if not obj.cover_image:
            return "No cover image"
        return format_html('<img src="{}" style="max-height:180px;border-radius:8px" />', obj.cover_image.url)

    # ------------------------------------------------------------------ actions
    @admin.action(description="Publish selected stories")
    def make_published(self, request, queryset):
        for article in queryset:
            article.publish()
        self.message_user(request, "{0} article(s) published.".format(queryset.count()))

    @admin.action(description="Move selected stories to draft")
    def make_draft(self, request, queryset):
        updated = queryset.update(status=Article.Status.DRAFT)
        self.message_user(request, "{0} article(s) moved to draft.".format(updated))

    @admin.action(description="Archive selected stories")
    def make_archived(self, request, queryset):
        updated = queryset.update(status=Article.Status.ARCHIVED)
        self.message_user(request, "{0} article(s) archived.".format(updated))

    @admin.action(description="Feature on the homepage")
    def feature(self, request, queryset):
        updated = queryset.update(is_featured=True)
        self.message_user(request, "{0} article(s) featured.".format(updated))

    @admin.action(description="Remove from the homepage")
    def unfeature(self, request, queryset):
        updated = queryset.update(is_featured=False)
        self.message_user(request, "{0} article(s) unfeatured.".format(updated))


@admin.register(Review)
class ReviewAdmin(admin.ModelAdmin):
    list_display = ("id", "article", "user", "rating", "created_at")
    list_filter = ("rating", "created_at")
    search_fields = ("comment", "user__username", "article__headline")
    autocomplete_fields = ("article", "user")
    date_hierarchy = "created_at"


@admin.register(Comment)
class CommentAdmin(admin.ModelAdmin):
    list_display = ("id", "article", "user", "short_body", "is_approved", "moderated_by", "created_at")
    list_filter = ("is_approved", "created_at")
    search_fields = ("body", "user__username", "article__headline")
    autocomplete_fields = ("article", "user")
    readonly_fields = ("moderated_at",)
    actions = ["approve_comments", "reject_comments"]

    @admin.display(description="comment")
    def short_body(self, obj):
        return obj.body[:60]

    @admin.action(description="Approve selected comments")
    def approve_comments(self, request, queryset):
        for comment in queryset:
            comment.approve(request.user, "Approved in bulk")
        self.message_user(request, "{0} comment(s) approved.".format(queryset.count()))

    @admin.action(description="Reject selected comments")
    def reject_comments(self, request, queryset):
        for comment in queryset:
            comment.reject(request.user, "Rejected in bulk")
        self.message_user(request, "{0} comment(s) rejected.".format(queryset.count()))


@admin.register(Bookmark)
class BookmarkAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "article", "created_at")
    search_fields = ("user__username", "article__headline")
    autocomplete_fields = ("user", "article")


@admin.register(ArticleView)
class ArticleViewAdmin(admin.ModelAdmin):
    list_display = ("id", "article", "user", "ip_address", "viewed_at")
    list_filter = ("viewed_at",)
    search_fields = ("article__headline",)
    date_hierarchy = "viewed_at"
