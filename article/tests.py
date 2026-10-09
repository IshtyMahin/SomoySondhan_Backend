"""Tests for the newsroom: articles, workflow, sections, reviews, comments,
bookmarks and the dashboard.

Run with:
    python manage.py test --settings=Somoysondhan.test_settings
"""

from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from article.models import Article, Bookmark, Category, Comment, Review, Tag
from reader.models import Profile

User = get_user_model()


class NewsroomMixin:
    password = "Str0ngPass!2024"

    def make_user(self, username, staff=False, superuser=False, role=None, active=True):
        user = User.objects.create_user(
            username=username, email="{0}@example.com".format(username), password=self.password
        )
        user.is_active = active
        user.is_staff = staff
        user.is_superuser = superuser
        user.save()
        profile, _ = Profile.objects.get_or_create(user=user)
        if role:
            profile.role = role
            profile.save(update_fields=["role"])
        return user

    def auth(self, user):
        response = self.client.post(
            "/user/login/", {"username": user.username, "password": self.password}, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.client.credentials(HTTP_AUTHORIZATION="Token " + response.data["token"])
        return response.data["token"]

    def logout_client(self):
        # Clearing credentials alone is not enough: the login view also opens a
        # session, and SessionAuthentication would keep honouring its cookie.
        self.client.credentials()
        self.client.logout()

    def make_section(self, name="Politics"):
        return Category.objects.create(name=name)

    def make_article(self, headline="A headline about the city budget", sections=None,
                     status_value=Article.Status.PUBLISHED, author=None, tags=None):
        article = Article.objects.create(
            headline=headline,
            body=" ".join(["word"] * 60),
            summary="A short standfirst.",
            status=status_value,
            author=author,
        )
        if sections:
            article.categories.set(sections)
        if tags:
            article.tags.set(tags)
        return article


class ArticleSetup(NewsroomMixin, APITestCase):
    def setUp(self):
        self.editor = self.make_user("editor", staff=True)
        self.reader = self.make_user("reader")
        self.section = self.make_section("Politics")
        self.sports = self.make_section("Sports")
        self.article = self.make_article(sections=[self.section], author=self.editor)


class ArticleReadTests(ArticleSetup):
    def test_list_is_public_and_returns_a_plain_array(self):
        """The deployed frontend expects [...], not {results: [...]}."""
        self.logout_client()
        response = self.client.get("/article/list/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIsInstance(response.data, list)
        self.assertEqual(len(response.data), 1)

    def test_list_preserves_the_frontend_field_contract(self):
        self.logout_client()
        item = self.client.get("/article/list/").data[0]
        for field in ("id", "headline", "body", "categories", "publishing_time",
                      "total_ratings", "average_rating"):
            self.assertIn(field, item, "frontend reads {0}".format(field))
        self.assertEqual(item["categories"], ["Politics"])

    def test_detail_includes_star_counts_for_the_rating_bars(self):
        self.logout_client()
        response = self.client.get("/article/list/{0}/".format(self.article.id))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("star_counts", response.data)
        self.assertEqual(set(response.data["star_counts"].keys()), {"1", "2", "3", "4"})
        self.assertIn("author_name", response.data)

    def test_category_filter_accepts_a_slug(self):
        self.logout_client()
        response = self.client.get("/article/list/?category=politics")
        self.assertEqual(len(response.data), 1)
        response = self.client.get("/article/list/?category=sports")
        self.assertEqual(len(response.data), 0)

    def test_paged_request_returns_the_envelope(self):
        self.make_article(headline="A second story about transport", sections=[self.section])
        self.logout_client()
        response = self.client.get("/article/list/?page=1&page_size=1")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("results", response.data)
        self.assertEqual(response.data["count"], 2)
        self.assertEqual(len(response.data["results"]), 1)

    def test_search_endpoint(self):
        self.logout_client()
        response = self.client.get("/article/list/search/?q=city")
        self.assertEqual(response.data["count"], 1)
        response = self.client.get("/article/list/search/?q=zzzz")
        self.assertEqual(response.data["count"], 0)

    def test_related_returns_other_stories_in_the_section(self):
        other = self.make_article(headline="Another politics story entirely", sections=[self.section])
        self.logout_client()
        response = self.client.get("/article/list/{0}/related/".format(self.article.id))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        ids = [item["id"] for item in response.data]
        self.assertIn(other.id, ids)
        self.assertNotIn(self.article.id, ids)

    def test_ordering_and_tag_filter(self):
        tag = Tag.objects.create(name="budget")
        self.article.tags.add(tag)
        self.logout_client()
        self.assertEqual(len(self.client.get("/article/list/?tag=budget").data), 1)
        self.assertEqual(len(self.client.get("/article/list/?tag=missing").data), 0)


class ArticleWritePermissionTests(ArticleSetup):
    def test_anonymous_cannot_create_an_article(self):
        """Previously anyone could POST an article."""
        self.logout_client()
        response = self.client.post(
            "/article/list/",
            {"headline": "Injected story headline", "body": "x" * 60, "categories": ["Politics"]},
            format="json",
        )
        self.assertIn(response.status_code, (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN))
        self.assertEqual(Article.objects.count(), 1)

    def test_reader_cannot_create_an_article(self):
        self.auth(self.reader)
        response = self.client.post(
            "/article/list/",
            {"headline": "Reader written story", "body": "x" * 60, "categories": ["Politics"]},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_reader_cannot_delete_an_article(self):
        self.auth(self.reader)
        response = self.client.delete("/article/list/{0}/".format(self.article.id))
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertTrue(Article.objects.filter(pk=self.article.id).exists())

    def test_editor_can_create_update_and_delete(self):
        self.auth(self.editor)
        response = self.client.post(
            "/article/list/",
            {
                "headline": "A fresh investigation into the port",
                "body": " ".join(["detail"] * 40),
                "categories": ["Politics"],
                "tags": ["ports", "trade"],
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        new_id = response.data["id"]
        self.assertEqual(response.data["author"], self.editor.id)
        self.assertEqual(sorted(response.data["tags"]), ["ports", "trade"])

        response = self.client.patch(
            "/article/list/{0}/".format(new_id), {"headline": "An updated port headline"}, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)

        response = self.client.delete("/article/list/{0}/".format(new_id))
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(Article.objects.filter(pk=new_id).exists())

    def test_create_requires_a_section(self):
        self.auth(self.editor)
        response = self.client.post(
            "/article/list/",
            {"headline": "A story with no section", "body": "x" * 60, "categories": []},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("categories", response.data)


class PublishWorkflowTests(ArticleSetup):
    def test_readers_cannot_see_drafts(self):
        self.make_article(headline="An unpublished draft story", sections=[self.section],
                          status_value=Article.Status.DRAFT)
        self.logout_client()
        response = self.client.get("/article/list/")
        self.assertEqual(len(response.data), 1, "the draft must stay hidden")

        self.auth(self.editor)
        response = self.client.get("/article/list/")
        self.assertEqual(len(response.data), 2, "an editor sees drafts too")

    def test_publish_moves_a_draft_live(self):
        draft = self.make_article(headline="Draft ready to go live", sections=[self.section],
                                  status_value=Article.Status.DRAFT)
        self.auth(self.editor)
        response = self.client.post("/article/list/{0}/publish/".format(draft.id))
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        draft.refresh_from_db()
        self.assertEqual(draft.status, Article.Status.PUBLISHED)

        self.logout_client()
        self.assertEqual(len(self.client.get("/article/list/").data), 2)

    def test_archive_hides_a_story_from_readers(self):
        self.auth(self.editor)
        response = self.client.post("/article/list/{0}/archive/".format(self.article.id))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.logout_client()
        self.assertEqual(len(self.client.get("/article/list/").data), 0)

    def test_feature_toggles_the_hero_flag(self):
        self.auth(self.editor)
        response = self.client.post("/article/list/{0}/feature/".format(self.article.id))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data["is_featured"])

        response = self.client.post("/article/list/{0}/feature/".format(self.article.id))
        self.assertFalse(response.data["is_featured"])

    def test_reader_cannot_publish(self):
        draft = self.make_article(headline="A draft nobody should publish", sections=[self.section],
                                  status_value=Article.Status.DRAFT)
        self.auth(self.reader)
        response = self.client.post("/article/list/{0}/publish/".format(draft.id))
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        draft.refresh_from_db()
        self.assertEqual(draft.status, Article.Status.DRAFT)


class ReviewTests(ArticleSetup):
    def test_signed_in_reader_can_review_and_totals_update(self):
        self.auth(self.reader)
        response = self.client.post(
            "/article/{0}/reviews/".format(self.article.id),
            {"rating": 4, "comment": "Sharp reporting throughout."},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        self.article.refresh_from_db()
        self.assertEqual(self.article.total_ratings, 1)
        self.assertEqual(self.article.total_stars, 4)
        self.assertEqual(self.article.average_rating, 4)

    def test_anonymous_cannot_review(self):
        self.logout_client()
        response = self.client.post(
            "/article/{0}/reviews/".format(self.article.id),
            {"rating": 3, "comment": "Not signed in."},
            format="json",
        )
        self.assertIn(response.status_code, (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN))

    def test_one_review_per_reader(self):
        self.auth(self.reader)
        self.client.post(
            "/article/{0}/reviews/".format(self.article.id),
            {"rating": 4, "comment": "First thoughts here."},
            format="json",
        )
        response = self.client.post(
            "/article/{0}/reviews/".format(self.article.id),
            {"rating": 2, "comment": "Second attempt here."},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(Review.objects.filter(article=self.article).count(), 1)

    def test_rating_must_be_one_to_four(self):
        self.auth(self.reader)
        response = self.client.post(
            "/article/{0}/reviews/".format(self.article.id),
            {"rating": 9, "comment": "Impossible rating."},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_reviews_are_public_to_read(self):
        Review.objects.create(article=self.article, user=self.reader, rating=3, comment="Fine.")
        self.logout_client()
        response = self.client.get("/article/{0}/reviews/".format(self.article.id))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)
        self.assertIn("display_name", response.data[0])

    def test_deleting_a_review_recalculates_the_average(self):
        """The old signal only fired on save, leaving stale averages."""
        first = Review.objects.create(article=self.article, user=self.reader, rating=4, comment="Good.")
        second = Review.objects.create(article=self.article, user=self.editor, rating=2, comment="Meh.")
        self.article.refresh_from_db()
        self.assertEqual(self.article.total_ratings, 2)
        self.assertEqual(self.article.average_rating, 3)

        first.delete()
        self.article.refresh_from_db()
        self.assertEqual(self.article.total_ratings, 1)
        self.assertEqual(self.article.average_rating, 2, "the average must drop after a delete")

    def test_a_reader_cannot_edit_someone_elses_review(self):
        review = Review.objects.create(article=self.article, user=self.editor, rating=3, comment="Mine.")
        self.auth(self.reader)
        response = self.client.patch(
            "/article/reviews/{0}/".format(review.id), {"rating": 1}, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)


class CommentTests(ArticleSetup):
    def test_reader_comment_waits_for_moderation(self):
        self.auth(self.reader)
        response = self.client.post(
            "/article/comments/",
            {"article": self.article.id, "body": "A reader comment awaiting approval."},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        self.assertFalse(response.data["is_approved"])

        # Not visible to the public yet.
        self.logout_client()
        self.assertEqual(len(self.client.get("/article/comments/?article={0}".format(self.article.id)).data), 0)

    def test_staff_comment_is_approved_immediately(self):
        self.auth(self.editor)
        response = self.client.post(
            "/article/comments/",
            {"article": self.article.id, "body": "A note from the newsroom desk."},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        self.assertTrue(response.data["is_approved"])

    def test_moderator_can_approve_a_pending_comment(self):
        comment = Comment.objects.create(
            article=self.article, user=self.reader, body="Pending comment text.", is_approved=False
        )
        self.auth(self.editor)
        response = self.client.post(
            "/article/comments/{0}/approve/".format(comment.id), {"note": "Looks fine"}, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        comment.refresh_from_db()
        self.assertTrue(comment.is_approved)
        self.assertEqual(comment.moderated_by, self.editor)

        self.logout_client()
        visible = self.client.get("/article/comments/?article={0}".format(self.article.id))
        self.assertEqual(len(visible.data), 1, "an approved comment becomes public")

    def test_reader_cannot_moderate(self):
        comment = Comment.objects.create(
            article=self.article, user=self.reader, body="Pending comment text.", is_approved=False
        )
        self.auth(self.reader)
        response = self.client.post("/article/comments/{0}/approve/".format(comment.id))
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_queue_lists_pending_comments_for_editors_only(self):
        Comment.objects.create(article=self.article, user=self.reader, body="Waiting.", is_approved=False)
        self.auth(self.reader)
        self.assertEqual(self.client.get("/article/comments/queue/").status_code, status.HTTP_403_FORBIDDEN)

        self.auth(self.editor)
        response = self.client.get("/article/comments/queue/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 1)

    def test_rejected_comment_disappears(self):
        comment = Comment.objects.create(
            article=self.article, user=self.reader, body="Bad comment.", is_approved=True
        )
        self.auth(self.editor)
        response = self.client.post("/article/comments/{0}/reject/".format(comment.id))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        comment.refresh_from_db()
        self.assertFalse(comment.is_approved)

    def test_comments_closed_on_a_story_block_new_ones(self):
        self.article.allow_comments = False
        self.article.save(update_fields=["allow_comments"])
        self.auth(self.reader)
        response = self.client.post(
            "/article/comments/",
            {"article": self.article.id, "body": "Should be refused."},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_reader_can_reply_to_a_comment(self):
        parent = Comment.objects.create(
            article=self.article, user=self.editor, body="Opening statement.", is_approved=True
        )
        self.auth(self.reader)
        response = self.client.post(
            "/article/comments/",
            {"article": self.article.id, "body": "A reply to the desk.", "parent": parent.id},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)


class BookmarkTests(ArticleSetup):
    def test_toggle_bookmark_saves_and_removes(self):
        self.auth(self.reader)
        response = self.client.post("/article/list/{0}/bookmark/".format(self.article.id))
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertTrue(response.data["bookmarked"])
        self.assertEqual(Bookmark.objects.filter(user=self.reader).count(), 1)

        response = self.client.post("/article/list/{0}/bookmark/".format(self.article.id))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(response.data["bookmarked"])
        self.assertEqual(Bookmark.objects.filter(user=self.reader).count(), 0)

    def test_bookmark_list_is_private(self):
        Bookmark.objects.create(user=self.reader, article=self.article)
        self.auth(self.editor)
        response = self.client.get("/article/bookmarks/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 0, "an editor must not see a reader's saves")

        self.auth(self.reader)
        response = self.client.get("/article/bookmarks/")
        self.assertEqual(len(response.data), 1)
        self.assertIn("article_detail", response.data[0])

    def test_bookmark_check_endpoint(self):
        Bookmark.objects.create(user=self.reader, article=self.article)
        self.auth(self.reader)
        response = self.client.get("/article/bookmarks/check/{0}/".format(self.article.id))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data["bookmarked"])

    def test_anonymous_cannot_bookmark(self):
        self.logout_client()
        response = self.client.get("/article/bookmarks/")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)


class ViewCountTests(ArticleSetup):
    def test_view_endpoint_increments_the_counter(self):
        self.logout_client()
        response = self.client.post("/article/list/{0}/view/".format(self.article.id))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["view_count"], 1)

        self.client.post("/article/list/{0}/view/".format(self.article.id))
        self.article.refresh_from_db()
        self.assertEqual(self.article.view_count, 2)

    def test_trending_orders_by_views(self):
        quiet = self.make_article(headline="A quiet story with few readers", sections=[self.section])
        self.article.view_count = 25
        self.article.save(update_fields=["view_count"])
        self.logout_client()
        response = self.client.get("/article/list/trending/")
        self.assertEqual(response.data[0]["id"], self.article.id)
        self.assertNotEqual(response.data[0]["id"], quiet.id)


class SectionAndTagTests(ArticleSetup):
    def test_sections_are_public_to_read(self):
        self.logout_client()
        response = self.client.get("/article/categories/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        names = [item["name"] for item in response.data]
        self.assertIn("Politics", names)
        for field in ("id", "name"):
            self.assertIn(field, response.data[0], "frontend reads {field}".format(field=field))

    def test_reader_cannot_create_a_section(self):
        """Previously anyone could POST a category."""
        self.auth(self.reader)
        response = self.client.post("/article/categories/", {"name": "Injected"}, format="json")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertFalse(Category.objects.filter(name="Injected").exists())

    def test_editor_can_create_a_section_and_slug_is_generated(self):
        self.auth(self.editor)
        response = self.client.post(
            "/article/categories/", {"name": "Climate Desk"}, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        self.assertEqual(response.data["slug"], "climate-desk")

    def test_anonymous_cannot_create_a_section(self):
        self.logout_client()
        response = self.client.post("/article/categories/", {"name": "Sneaky"}, format="json")
        self.assertIn(response.status_code, (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN))

    def test_tags_are_created_implicitly_with_an_article(self):
        self.auth(self.editor)
        self.client.post(
            "/article/list/",
            {
                "headline": "A tagged story about the river",
                "body": "x" * 60,
                "categories": ["Politics"],
                "tags": ["rivers", "climate"],
            },
            format="json",
        )
        self.assertEqual(Tag.objects.count(), 2)
        self.assertTrue(Tag.objects.filter(name="rivers").exists())


class DashboardTests(ArticleSetup):
    def test_stats_require_editorial_access(self):
        self.logout_client()
        self.assertEqual(self.client.get("/article/stats/").status_code, status.HTTP_401_UNAUTHORIZED)

        self.auth(self.reader)
        self.assertEqual(self.client.get("/article/stats/").status_code, status.HTTP_403_FORBIDDEN)

        self.auth(self.editor)
        response = self.client.get("/article/stats/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["articles"]["published"], 1)
        self.assertIn("engagement", response.data)
        self.assertIn("top_stories", response.data)


class ModelBehaviourTests(ArticleSetup):
    def test_reading_minutes_is_at_least_one(self):
        short = self.make_article(headline="A very short story", sections=[self.section])
        short.body = "three words only"
        self.assertEqual(short.reading_minutes, 1)

    def test_category_slug_is_generated_on_save(self):
        section = Category.objects.create(name="World News")
        self.assertEqual(section.slug, "world-news")

    def test_publish_sets_the_timestamp(self):
        draft = self.make_article(headline="A draft to schedule", sections=[self.section],
                                  status_value=Article.Status.DRAFT)
        when = timezone.now()
        draft.publish(when=when)
        draft.refresh_from_db()
        self.assertEqual(draft.status, Article.Status.PUBLISHED)
        self.assertAlmostEqual(draft.publishing_time, when, delta=timezone.timedelta(seconds=2))
