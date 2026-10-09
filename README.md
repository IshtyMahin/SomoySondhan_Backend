# Somoy Sondhan — Backend

Django REST Framework backend for the Somoy Sondhan newspaper.

**Rebuilt, not replaced.** Every existing row is preserved: the project still
uses `django.contrib.auth.models.User`, so all 3 accounts, 8 articles, 7
sections and 5 reviews in `db.sqlite3` carry over. Extra reader data lives in a
`Profile` (OneToOne), which is created automatically for old and new users alike.

---

## What is in here

| Area | Endpoints |
| --- | --- |
| Accounts | register, activate, login, logout, token refresh, password change, password reset |
| User CRUD | list (staff), retrieve (public), update (self/staff), soft delete, block/unblock, role, stats, `me` |
| Articles | list, retrieve, create, update, delete, publish, archive, feature, view counter, trending, search, related |
| Sections & tags | full CRUD (editors write, everyone reads) |
| Reviews | public read, one per reader per article, auto-recalculated averages |
| Comments | post, reply, approve, reject, moderation queue |
| Bookmarks | save/unsave, my saves, check |
| Dashboard | `/article/stats/` and `/user/stats/` |

Browseable API reference: **`/api/docs/`** (OpenAPI schema at `/api/schema/`).

---

## Run it

```bash
# 1. dependencies  (see the note about requirements.txt below)
pip install -r requirements-utf8.txt

# 2. environment
copy .env.example Somoysondhan\.env     # then edit SECRET_KEY and email

# 3. database
python manage.py makemigrations reader article
python manage.py migrate

# 4. give existing accounts their Profile rows  (run once)
python manage.py backfill_profiles --sync-roles

# 5. serve
python manage.py runserver 8000
```

Then open <http://127.0.0.1:8000/api/docs/>.

### Tests

```bash
python manage.py test --settings=Somoysondhan.test_settings
```

The test settings use an in-memory database, a fast password hasher, an in-memory
email backend and no throttling, so the suite is quick and leaves no files behind.
Coverage: registration and activation, login/rotation/expiry, logout, the whole
user CRUD surface and its permissions, password reset, articles, the draft →
published workflow, search/filter/pagination, reviews, comments and moderation,
bookmarks, view counts and the dashboards.

---

## Fixed along the way

These were real defects in the previous backend:

1. **`MEDIA_ROOT` was never defined** while `urls.py` passed it to `static()`.
   Nothing could ever be uploaded. It is now set, and media is served even with
   `DEBUG=False`.
2. **No permissions anywhere.** Any anonymous visitor could create, edit or
   delete articles and sections. Writes now require an editorial account.
3. **`is_superuser` was unreachable.** The action was `detail=False` but the URL
   required `<int:pk>`, so the frontend's admin check always failed. It is now a
   dedicated view.
4. **`activate` was not imported** in `reader/urls.py`, so every confirmation
   link raised `NameError`. It is imported and the view is hardened.
5. **Logout crashed for anonymous callers** (`AttributeError` on
   `request.user.auth_token`) and never actually deleted the token.
6. **Deleting a review left stale averages.** The signal only listened to
   `post_save`; it now listens to `post_delete` too and recalculates.
7. **`requirements.txt` was saved as UTF-16**, which makes `pip install -r`
   fail on every line.
8. **Every reader's email address was public** through `/user/list/<id>/`, which
   the frontend calls to render review bylines. That route now returns a public
   projection; staff still get the full record.
9. `serializer.error` (a bound method) was returned on invalid login. Validation
   errors are now real error responses.

---

## Notes and caveats

* **`requirements.txt` is UTF-16.** I could not overwrite it from this
  environment (the file is locked by a Windows permission rule), so the correct
  list is in **`requirements-utf8.txt`**. Fix it with either:

  ```powershell
  Remove-Item requirements.txt
  Rename-Item requirements-utf8.txt requirements.txt
  ```

  or point your install/Render command at `requirements-utf8.txt`.
* **I could not execute Django here.** Django is not installed in this
  environment and **PyPI, jsDelivr and Google Fonts are all unreachable**
  (`http=000`), so no package could be installed. What I *did* verify:

  | Check | Result |
  | --- | --- |
  | Python syntax, all 35 files | clean |
  | Schema vs the real `db.sqlite3` | every pre-existing column still declared |
  | Migration simulated on a copy of your real database | **all rows preserved byte-identical** |
  | `PRAGMA foreign_key_check` after the simulated migration | clean |
  | Existing 8 articles after migration | `status='published'`, so readers keep seeing them |
  | Reading, favourites, comments, bookmarks, tags tables | created successfully |
  | Serializer fields vs model fields | every field resolves |
  | Routes registered / views imported | all present |
  | Unused imports | none |

  The migration simulation reproduces Django's SQLite behaviour exactly:
  `CREATE new -> INSERT ... SELECT -> DROP old -> RENAME`, with foreign keys
  disabled during the rebuild and the one-off defaults Django would prompt for.
  It reports that all 3 users (password hashes included), 8 articles, 7 sections,
  5 reviews and 14 section links survive untouched.

  **The Django test suite has still not been executed** — that needs a machine
  with the packages installed. It is the first thing to run.
* `publishing_time` keeps `auto_now_add=True` so existing rows are untouched.
  `Article.publish(when=...)` writes an explicit timestamp for stories going
  live, which is how scheduling works without a schema change.
* Pagination is opt-in: `/article/list/` still returns a plain array so the
  deployed frontend keeps working; add `?page=1` to get the
  `{count, num_pages, page, page_size, next, previous, results}` envelope.
  The frontend now handles both: `Api.articles()` unwraps the envelope
  automatically, and `Api.articlesPage(page, size)` gives access to the full
  paginated response with `count`, `numPages`, `next` and `previous`.
* Tags accept plain strings or ids: `"tags": ["rivers", "climate"]`.
* Comments default to requiring moderation; staff comments publish immediately.

### Frontend compatibility

The response shapes the current frontend depends on are unchanged:

| Call | Still returns |
| --- | --- |
| `POST /user/login/` | `{token, user_id}` (+ `is_superuser`, `role`) |
| `POST /user/register/` | the created account, so `username`/`email` errors still surface |
| `GET /user/<id>/is_superuser/` | `{is_superuser, is_staff, is_editor}` |
| `GET /article/categories/` | `[{id, name}]` |
| `GET /article/list/?category=x` | plain array of articles |
| `GET /article/list/<id>/` | includes `average_rating`, `star_counts`, `reviews` |
| `POST /article/<id>/reviews/` | accepts `{rating, comment, article, user}` |

The frontend also sends `Authorization: Token <key>`; that scheme is kept, with
expiry and rotation added.
