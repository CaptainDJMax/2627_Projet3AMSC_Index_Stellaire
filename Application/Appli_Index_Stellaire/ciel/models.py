from django.db import models

from django.conf import settings

from .astro import altaz


class ObjetCeleste(models.Model):
    class Categorie(models.TextChoices):
        ETOILE = "etoile", "Étoile"
        PLANETE = "planete", "Planète"
        LUNE = "lune", "Lune"
        AMAS = "amas", "Amas"
        SATELLITE = "satellite", "Satellite"

    nom = models.CharField(max_length=100)
    categorie = models.CharField(max_length=20, choices=Categorie.choices)
    identifiant_skyfield = models.CharField(
        max_length=50,
        blank=True,
        default="",
        help_text="Étoile : hip:NUMERO (ex. hip:21421). "
        "Planète : nom de l'éphéméride (ex. jupiter barycenter).",
    )
    description = models.TextField(blank=True)
    image = models.ImageField(upload_to="objets_celestes/", blank=True, null=True)

    def __str__(self):
        return self.nom

    def position(self, lieu=None, instant=None):
        """(élévation, azimut) en degrés, ou None si l'objet n'a pas
        d'identifiant Skyfield. lieu : dict latitude/longitude/altitude_m."""
        if not self.identifiant_skyfield:
            return None
        lieu = lieu or settings.LIEU_PAR_DEFAUT
        return altaz(
            self.identifiant_skyfield,
            lieu["latitude"],
            lieu["longitude"],
            lieu.get("altitude_m", 0),
            instant,
        )


class Constellation(models.Model):
    nom = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    image = models.ImageField(upload_to="constellations/", blank=True, null=True)
    etoiles = models.ManyToManyField(
        ObjetCeleste,
        limit_choices_to={"categorie": ObjetCeleste.Categorie.ETOILE},
        related_name="constellations",
        blank=True,
    )

    def __str__(self):
        return self.nom
