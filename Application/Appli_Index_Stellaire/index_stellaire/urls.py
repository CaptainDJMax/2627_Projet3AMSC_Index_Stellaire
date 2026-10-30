from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path, re_path
from django.views.static import serve

from ciel import views as vues_ciel

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/ciel/", include("ciel.urls")),
    path("api/", include("appareil.urls")),
    path("", vues_ciel.carte, name="carte"),
] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

if not settings.DEBUG:
    # Partie 14 : `static()` ne fait rien en production ; les images des fiches (media/) doivent
    # pourtant rester visibles. Une seule personne, quelques images : Django suffit à les servir.
    urlpatterns.append(re_path(r"^media/(?P<path>.*)$", serve, {"document_root": settings.MEDIA_ROOT}))
