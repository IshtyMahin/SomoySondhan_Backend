"""
Root URL configuration.

  /admin/       Django admin
  /user/        authentication and reader accounts
  /article/     articles, sections, tags, reviews, comments, bookmarks, stats
  /api/schema/  OpenAPI schema
  /api/docs/    browseable API reference
  /media/...    uploaded files (covers, avatars)
"""

from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path, re_path
from django.views.static import serve
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

urlpatterns = [
    path("admin/", admin.site.urls),

    path("user/", include("reader.urls")),
    path("article/", include("article.urls")),

    # API documentation
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path(
        "api/docs/",
        SpectacularSwaggerView.as_view(url_name="schema"),
        name="swagger-ui",
    ),
]

# Uploaded media. `static()` only works with DEBUG=True, so an explicit route is
# added for production too — otherwise every cover image and avatar 404s on the
# deployed backend. For heavy traffic, serve MEDIA_ROOT from the web server or a
# bucket instead.
urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
urlpatterns += [
    re_path(r"^media/(?P<path>.*)$", serve, {"document_root": settings.MEDIA_ROOT}),
]
