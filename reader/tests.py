"""Tests for reader accounts, authentication and user CRUD.

Run with:
    python manage.py test --settings=Somoysondhan.test_settings
"""

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core import mail
from django.test import override_settings
from rest_framework import status
from rest_framework.authtoken.models import Token
from rest_framework.test import APITestCase

from reader.models import Profile

User = get_user_model()


class UserFactoryMixin:
    """Small helpers so each test states only what it cares about."""

    password = "Str0ngPass!2024"

    def make_user(self, username="reader1", email=None, active=True, staff=False,
                  superuser=False, role=None):
        user = User.objects.create_user(
            username=username,
            email=email or "{0}@example.com".format(username),
            password=self.password,
            first_name="Test",
            last_name="Reader",
        )
        user.is_active = active
        user.is_staff = staff
        user.is_superuser = superuser
        user.save()
        profile, _ = Profile.objects.get_or_create(user=user)
        if role:
            profile.role = role
            profile.save(update_fields=["role"])
            # `user.profile` may already hold a stale cached instance from the
            # post_save signal; point it at the row we just updated.
            user.profile = profile
        return user

    def login(self, user):
        """Authenticate the client and return the token."""
        response = self.client.post(
            "/user/login/", {"username": user.username, "password": self.password}, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        token = response.data["token"]
        self.client.credentials(HTTP_AUTHORIZATION="Token " + token)
        return token


class RegistrationTests(UserFactoryMixin, APITestCase):
    url = "/user/register/"

    def payload(self, **overrides):
        data = {
            "username": "newreader",
            "first_name": "New",
            "last_name": "Reader",
            "email": "new@example.com",
            "password": "Str0ngPass!2024",
            "confirm_password": "Str0ngPass!2024",
        }
        data.update(overrides)
        return data

    def test_register_creates_inactive_reader_and_emails_a_link(self):
        response = self.client.post(self.url, self.payload(), format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        user = User.objects.get(username="newreader")
        self.assertFalse(user.is_active, "a new account must confirm its email first")
        self.assertTrue(hasattr(user, "profile"), "a Profile row must be created automatically")
        self.assertFalse(user.profile.email_confirmed)
        self.assertEqual(len(mail.outbox), 1, "a confirmation email should be sent")
        self.assertIn("/user/active/", mail.outbox[0].body)

    def test_register_rejects_mismatched_passwords(self):
        response = self.client.post(
            self.url, self.payload(confirm_password="SomethingElse!2024"), format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("confirm_password", response.data)

    def test_register_rejects_duplicate_username(self):
        self.make_user(username="taken", email="taken@example.com")
        response = self.client.post(
            self.url, self.payload(username="taken", email="fresh@example.com"), format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("username", response.data)

    def test_register_rejects_duplicate_email(self):
        self.make_user(username="taken", email="taken@example.com")
        response = self.client.post(
            self.url, self.payload(username="freshname", email="taken@example.com"), format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("email", response.data)

    def test_register_rejects_weak_password(self):
        response = self.client.post(
            self.url, self.payload(password="123", confirm_password="123"), format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("password", response.data)

    def test_activation_link_activates_the_account(self):
        self.client.post(self.url, self.payload(username="activate_me"), format="json")
        body = mail.outbox[0].body
        path = body.split("/user/active/")[1].split()[0].strip()
        response = self.client.get("/user/active/" + path)
        self.assertIn(response.status_code, (301, 302))

        user = User.objects.get(username="activate_me")
        self.assertTrue(user.is_active)
        self.assertTrue(user.profile.email_confirmed)
        self.assertIsNotNone(user.profile.email_confirmed_at)


class LoginTests(UserFactoryMixin, APITestCase):
    url = "/user/login/"

    def test_login_returns_the_keys_the_frontend_reads(self):
        user = self.make_user()
        response = self.client.post(
            self.url, {"username": user.username, "password": self.password}, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("token", response.data)
        self.assertIn("user_id", response.data)
        self.assertEqual(response.data["user_id"], user.id)

    def test_login_rotates_the_token(self):
        user = self.make_user()
        first = self.client.post(
            self.url, {"username": user.username, "password": self.password}, format="json"
        ).data["token"]
        second = self.client.post(
            self.url, {"username": user.username, "password": self.password}, format="json"
        ).data["token"]
        self.assertNotEqual(first, second, "each sign-in should replace the old key")
        self.assertEqual(Token.objects.filter(user=user).count(), 1)

    def test_login_rejects_wrong_password(self):
        user = self.make_user()
        response = self.client.post(
            self.url, {"username": user.username, "password": "nope"}, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("error", response.data)

    def test_login_rejects_unknown_user(self):
        response = self.client.post(
            self.url, {"username": "ghost", "password": "nope"}, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("error", response.data)

    def test_inactive_account_cannot_sign_in(self):
        user = self.make_user(username="unconfirmed", active=False)
        response = self.client.post(
            self.url, {"username": user.username, "password": self.password}, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("confirm", str(response.data).lower())

    def test_blocked_reader_cannot_sign_in(self):
        user = self.make_user()
        user.profile.is_blocked = True
        user.profile.save(update_fields=["is_blocked"])
        response = self.client.post(
            self.url, {"username": user.username, "password": self.password}, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("suspended", str(response.data).lower())


class TokenLifecycleTests(UserFactoryMixin, APITestCase):
    def test_logout_deletes_the_token(self):
        user = self.make_user()
        self.login(user)
        response = self.client.post("/user/logout/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(Token.objects.filter(user=user).count(), 0)
        response = self.client.get("/user/me/")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_logout_while_anonymous_is_rejected_not_crashed(self):
        """The old view raised AttributeError on an anonymous request."""
        response = self.client.post("/user/logout/")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_refresh_rotates_the_token(self):
        user = self.make_user()
        old = self.login(user)
        response = self.client.post("/user/token/refresh/")
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertNotEqual(response.data["token"], old)

    @override_settings(TOKEN_TTL=timedelta(seconds=-1))
    def test_expired_token_is_rejected(self):
        user = self.make_user()
        self.login(user)
        response = self.client.get("/user/me/")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_missing_token_is_rejected(self):
        self.client.credentials()
        response = self.client.get("/user/me/")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)


class UserCrudTests(UserFactoryMixin, APITestCase):
    def setUp(self):
        self.reader = self.make_user(username="reader")
        self.other = self.make_user(username="other")
        self.editor = self.make_user(username="editor", staff=True)

    def test_me_returns_own_account_with_profile(self):
        self.login(self.reader)
        response = self.client.get("/user/me/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["username"], "reader")
        self.assertIn("profile", response.data)

    def test_reader_directory_is_staff_only(self):
        self.login(self.reader)
        self.assertEqual(self.client.get("/user/list/").status_code, status.HTTP_403_FORBIDDEN)

        self.login(self.editor)
        response = self.client.get("/user/list/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_public_profile_never_exposes_email(self):
        """Another reader's record must not leak their address."""
        self.login(self.reader)
        response = self.client.get("/user/list/{0}/".format(self.other.id))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertNotIn("email", response.data)
        self.assertIn("display_name", response.data)

    def test_owner_can_update_their_profile(self):
        self.login(self.reader)
        response = self.client.patch(
            "/user/list/{0}/".format(self.reader.id),
            {"first_name": "Changed", "profile": {"bio": "Hello there", "location": "Dhaka"}},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.reader.refresh_from_db()
        self.reader.profile.refresh_from_db()
        self.assertEqual(self.reader.first_name, "Changed")
        self.assertEqual(self.reader.profile.bio, "Hello there")

    def test_reader_cannot_update_someone_else(self):
        self.login(self.reader)
        response = self.client.patch(
            "/user/list/{0}/".format(self.other.id), {"first_name": "Hacked"}, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_staff_can_update_anyone(self):
        self.login(self.editor)
        response = self.client.patch(
            "/user/list/{0}/".format(self.reader.id), {"first_name": "Edited"}, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)

    def test_password_change_requires_the_current_password_and_rotates_the_token(self):
        old_token = self.login(self.reader)
        response = self.client.post(
            "/user/password/change/",
            {"current_password": "wrong", "new_password": "An0ther!Pass99"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        response = self.client.post(
            "/user/password/change/",
            {"current_password": self.password, "new_password": "An0ther!Pass99"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertNotEqual(response.data["token"], old_token)
        self.reader.refresh_from_db()
        self.assertTrue(self.reader.check_password("An0ther!Pass99"))

    def test_soft_delete_deactivates_own_account(self):
        self.login(self.reader)
        response = self.client.delete("/user/me/delete/")
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.reader.refresh_from_db()
        self.assertFalse(self.reader.is_active)

    def test_staff_can_block_and_unblock_a_reader(self):
        self.login(self.editor)
        response = self.client.post("/user/list/{0}/block/".format(self.reader.id))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.reader.profile.refresh_from_db()
        self.assertTrue(self.reader.profile.is_blocked)

        response = self.client.post("/user/list/{0}/unblock/".format(self.reader.id))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.reader.profile.refresh_from_db()
        self.assertFalse(self.reader.profile.is_blocked)

    def test_reader_cannot_block_anyone(self):
        self.login(self.reader)
        response = self.client.post("/user/list/{0}/block/".format(self.other.id))
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_staff_cannot_block_themselves(self):
        self.login(self.editor)
        response = self.client.post("/user/list/{0}/block/".format(self.editor.id))
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_staff_can_change_a_role(self):
        self.login(self.editor)
        response = self.client.post(
            "/user/list/{0}/role/".format(self.reader.id), {"role": "author"}, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.reader.profile.refresh_from_db()
        self.assertEqual(self.reader.profile.role, Profile.Role.AUTHOR)

        response = self.client.post(
            "/user/list/{0}/role/".format(self.reader.id), {"role": "wizard"}, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_is_superuser_endpoint_matches_the_frontend_contract(self):
        """This route used to be unreachable: the action was detail=False while
        the URL pattern required a pk."""
        response = self.client.get("/user/{0}/is_superuser/".format(self.editor.id))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("is_superuser", response.data)
        self.assertTrue(response.data["is_superuser"])

        response = self.client.get("/user/{0}/is_superuser/".format(self.reader.id))
        self.assertFalse(response.data["is_superuser"])

        response = self.client.get("/user/999999/is_superuser/")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_stats_are_staff_only_and_count_correctly(self):
        self.login(self.reader)
        self.assertEqual(self.client.get("/user/stats/").status_code, status.HTTP_403_FORBIDDEN)

        self.login(self.editor)
        response = self.client.get("/user/stats/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["total"], 3)
        self.assertGreaterEqual(response.data["staff"], 1)


class PasswordResetTests(UserFactoryMixin, APITestCase):
    def test_reset_request_is_always_accepted(self):
        """Must not reveal whether an address is registered."""
        self.make_user(username="forgot", email="forgot@example.com")
        for email in ("forgot@example.com", "nobody@example.com"):
            response = self.client.post("/user/password/reset/", {"email": email}, format="json")
            self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(mail.outbox), 1, "only the real address gets an email")

    def test_reset_confirm_sets_a_new_password(self):
        user = self.make_user(username="resetme", email="reset@example.com")
        self.client.post("/user/password/reset/", {"email": "reset@example.com"}, format="json")
        body = mail.outbox[0].body
        query = body.split("reset.html?")[1].split()[0]
        params = dict(part.split("=") for part in query.split("&"))

        response = self.client.post(
            "/user/password/reset/confirm/",
            {
                "uid": params["uid"],
                "token": params["token"],
                "new_password": "BrandNew!Pass77",
                "confirm_password": "BrandNew!Pass77",
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        user.refresh_from_db()
        self.assertTrue(user.check_password("BrandNew!Pass77"))

    def test_reset_confirm_rejects_a_bad_token(self):
        self.make_user(username="badtoken", email="bad@example.com")
        response = self.client.post(
            "/user/password/reset/confirm/",
            {"uid": "abc", "token": "nope", "new_password": "BrandNew!Pass77"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


class ProfileModelTests(UserFactoryMixin, APITestCase):
    def test_superuser_and_staff_are_treated_as_editors(self):
        superuser = self.make_user(username="su", superuser=True)
        staff = self.make_user(username="st", staff=True)
        plain = self.make_user(username="plain")
        author = self.make_user(username="au", role=Profile.Role.AUTHOR)

        self.assertTrue(superuser.profile.is_editor)
        self.assertTrue(staff.profile.is_editor)
        self.assertTrue(author.profile.is_editor)
        self.assertFalse(plain.profile.is_editor)

    def test_display_name_falls_back_to_username(self):
        user = self.make_user(username="noname")
        user.first_name = ""
        user.last_name = ""
        user.save()
        self.assertEqual(user.profile.display_name, "noname")

    def test_profile_is_created_for_a_user_made_without_one(self):
        """Covers accounts that predate the model."""
        user = User.objects.create(username="legacy", email="legacy@example.com")
        Profile.objects.filter(user=user).delete()
        user.save()  # triggers the post_save signal
        self.assertTrue(Profile.objects.filter(user=user).exists())
