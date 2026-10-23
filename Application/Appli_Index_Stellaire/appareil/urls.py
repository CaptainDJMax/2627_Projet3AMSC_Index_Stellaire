from django.urls import path

from . import views

app_name = "appareil"

urlpatterns = [
    # Côté appareil (jeton)
    path("appareil/sync/", views.synchroniser, name="sync"),
    # Côté interface web
    path("pointage/", views.etat_pointage, name="etat"),
    path("pointage/commande/", views.definir_commande, name="commande"),
    path("pointage/arret/", views.arreter_pointage, name="arret"),
]
