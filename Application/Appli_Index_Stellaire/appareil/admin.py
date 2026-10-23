from django.contrib import admin

from .models import Appareil, Commande


@admin.register(Appareil)
class AppareilAdmin(admin.ModelAdmin):
    list_display = ("nom", "mode", "batterie", "derniere_vue")
    # Le jeton se lit ici une fois pour le copier dans l'appareil ; il ne se modifie pas
    readonly_fields = ("jeton", "derniere_vue", "azimut", "elevation", "batterie", "mode")


@admin.register(Commande)
class CommandeAdmin(admin.ModelAdmin):
    list_display = ("appareil", "objet", "cree_le", "active")
    list_filter = ("active",)
