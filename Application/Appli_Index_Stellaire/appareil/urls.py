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
    # Partie 5 : code de pilotage
    path("pointage/pilotage/", views.ouvrir_pilotage, name="pilotage"),
    path("pointage/pilotage/fin/", views.fermer_pilotage, name="pilotage_fin"),
]
