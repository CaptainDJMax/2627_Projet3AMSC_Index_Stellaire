from django.contrib import admin
from .models import ObjetCeleste, Constellation


@admin.register(ObjetCeleste)
class ObjetCelesteAdmin(admin.ModelAdmin):
    list_display = ("nom", "categorie", "identifiant_skyfield")
    list_filter = ("categorie",)


@admin.register(Constellation)
class ConstellationAdmin(admin.ModelAdmin):
    filter_horizontal = ("etoiles",)
