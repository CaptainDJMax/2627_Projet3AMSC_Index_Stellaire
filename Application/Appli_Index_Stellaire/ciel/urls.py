from django.urls import path

from . import journal, views

app_name = "ciel"

urlpatterns = [
    path("objets/", views.liste_objets, name="objets"),
    path("objets/<int:objet_id>/", views.detail_objet, name="objet"),
    path("evenements/", views.evenements, name="evenements"),  # Partie 7
    path("point/", views.point, name="point"),  # Partie 8.4 : cible personnalisée
    path("lieu/", views.partager_lieu, name="lieu"),  # Partie 6.4
    # Partie 9 : journal d'observation
    path("journal/", journal.lire, name="journal"),
    path("journal/noter/", journal.noter, name="journal_noter"),
    path("journal/<int:observation_id>/effacer/", journal.effacer, name="journal_effacer"),
    path("journal/export.csv", journal.exporter, name="journal_export"),
]
