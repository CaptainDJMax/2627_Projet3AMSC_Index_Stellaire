import secrets
from datetime import timedelta

from django.db import models
from django.db.models import Q
from django.utils import timezone

from ciel.models import ObjetCeleste

# Au-delà de ce délai sans nouvelles, l'appareil est considéré hors ligne
DELAI_HORS_LIGNE = timedelta(seconds=10)


def nouveau_jeton():
    """Secret propre à l'appareil : l'ESP32 le présente à chaque requête."""
    return secrets.token_urlsafe(32)


class Appareil(models.Model):
    class Mode(models.TextChoices):
        REPOS = "repos", "Au repos"
        DEPLACEMENT = "deplacement", "En déplacement"
        SUIVI = "suivi", "En suivi"
        ERREUR = "erreur", "Erreur"

    nom = models.CharField(max_length=100, default="Index Stellaire")
    jeton = models.CharField(max_length=64, unique=True, default=nouveau_jeton, editable=False)

    # Dernier état rapporté par l'appareil lui-même
    derniere_vue = models.DateTimeField(null=True, blank=True)
    azimut = models.FloatField(null=True, blank=True)  # degrés, 0 = nord, sens horaire
    elevation = models.FloatField(null=True, blank=True)  # degrés, négatif = sous l'horizon
    batterie = models.PositiveSmallIntegerField(null=True, blank=True)  # pourcentage
    mode = models.CharField(max_length=20, choices=Mode.choices, default=Mode.REPOS)

    # Partie 6.2 : lieu rapporté par le GPS de l'appareil (vide tant qu'il n'a rien envoyé)
    latitude = models.FloatField(null=True, blank=True)  # degrés, nord positif
    longitude = models.FloatField(null=True, blank=True)  # degrés, est positif
    altitude_m = models.FloatField(null=True, blank=True)  # mètres au-dessus de l'ellipsoïde
    lieu_mis_a_jour = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return self.nom

    @property
    def connecte(self):
        return self.derniere_vue is not None and timezone.now() - self.derniere_vue < DELAI_HORS_LIGNE


NOM_POINT_DU_CIEL = "Point du ciel"


class Commande(models.Model):
    """Ce que l'utilisateur demande au bras : pointer un objet, en continu.

    Partie 8.4 (cible personnalisée, F18) : sans objet, la cible est un point fixe du ciel donné
    par ses coordonnées (ra, dec) ; il tourne avec le ciel, comme une étoile, et peut être sous
    l'horizon (le bras pointe alors à travers la Terre)."""

    appareil = models.ForeignKey(Appareil, on_delete=models.CASCADE, related_name="commandes")
    objet = models.ForeignKey(
        ObjetCeleste, on_delete=models.CASCADE, related_name="commandes", null=True, blank=True
    )
    ra = models.FloatField(null=True, blank=True)  # ascension droite (degrés, J2000), point du ciel
    dec = models.FloatField(null=True, blank=True)  # déclinaison (degrés, J2000)
    nom_cible = models.CharField(max_length=60, blank=True, default="")
    cree_le = models.DateTimeField(auto_now_add=True)
    active = models.BooleanField(default=True)

    class Meta:
        ordering = ["-cree_le"]
        constraints = [
            # Soit un objet, soit des coordonnées (point du ciel)
            models.CheckConstraint(
                condition=Q(objet__isnull=False) | (Q(ra__isnull=False) & Q(dec__isnull=False)),
                name="objet_ou_coordonnees",
            ),
            # Au plus une commande active par appareil
            models.UniqueConstraint(
                fields=["appareil"], condition=Q(active=True), name="une_commande_active_par_appareil"
            ),
        ]

    @property
    def identifiant(self):
        """Ce que ciel.astro sait calculer : celui de l'objet, ou « radec:RA,DEC » pour un point."""
        if self.objet is not None:
            return self.objet.identifiant_skyfield
        return f"radec:{self.ra},{self.dec}"

    @property
    def nom(self):
        return self.objet.nom if self.objet is not None else (self.nom_cible or NOM_POINT_DU_CIEL)

    @property
    def coordonnees(self):
        """{ra, dec} pour un point du ciel, None pour un objet de la base."""
        return None if self.objet is not None else {"ra": self.ra, "dec": self.dec}

    def resume_objet(self):
        """Le champ « objet » des réponses : id None pour un point du ciel (8.4)."""
        return {"id": self.objet.id if self.objet is not None else None, "nom": self.nom}

    def __str__(self):
        return f"{self.appareil} → {self.nom}" + ("" if self.active else " (terminée)")
