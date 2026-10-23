from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

from ciel import views as vues_ciel

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/ciel/", include("ciel.urls")),
    path("api/", include("appareil.urls")),
    path("", vues_ciel.carte, name="carte"),
] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
