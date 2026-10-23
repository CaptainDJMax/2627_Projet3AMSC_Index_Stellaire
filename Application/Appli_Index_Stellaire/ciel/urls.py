from django.urls import path

from . import views

app_name = "ciel"

urlpatterns = [
    path("objets/", views.liste_objets, name="objets"),
    path("objets/<int:objet_id>/", views.detail_objet, name="objet"),
]
