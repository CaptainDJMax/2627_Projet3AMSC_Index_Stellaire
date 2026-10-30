from django.urls import path

from . import apercu, views

app_name = "appareil"

urlpatterns = [
    # Côté appareil (jeton)
    path("appareil/sync/", views.synchroniser, name="sync"),
    path("appareil/trajectoire/", views.trajectoire_appareil, name="trajectoire"),  # Partie 6.1
    # Côté interface web
    path("pointage/", views.etat_pointage, name="etat"),
    path("pointage/commande/", views.definir_commande, name="commande"),
    path("pointage/arret/", views.arreter_pointage, name="arret"),
    path("pointage/visite/", views.definir_visite, name="visite"),  # Partie 8.5
    path("pointage/visite/apercu/", apercu.apercu_visite, name="visite_apercu"),  # 14.1 bis : horaires et hauteurs
    # Partie 5 : code de pilotage
    path("pointage/pilotage/", views.ouvrir_pilotage, name="pilotage"),
    path("pointage/pilotage/fin/", views.fermer_pilotage, name="pilotage_fin"),
]
