from django.db import models


class ObjetCeleste(models.Model):
    class Categorie(models.TextChoices):
        ETOILE = "etoile", "Étoile"
        PLANETE = "planete", "Planète"
        AMAS = "amas", "Amas"
        SATELLITE = "satellite", "Satellite"

    nom = models.CharField(max_length=100)
    categorie = models.CharField(max_length=20, choices=Categorie.choices)
    description = models.TextField(blank=True)
    image = models.ImageField(upload_to="objets_celestes/", blank=True, null=True)

    def __str__(self):
        return self.nom
