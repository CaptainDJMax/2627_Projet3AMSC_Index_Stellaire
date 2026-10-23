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

    def __str__(self):
        return self.nom

    @property
    def connecte(self):
        return self.derniere_vue is not None and timezone.now() - self.derniere_vue < DELAI_HORS_LIGNE


class Commande(models.Model):
    """Ce que l'utilisateur demande au bras : pointer un objet, en continu."""

    appareil = models.ForeignKey(Appareil, on_delete=models.CASCADE, related_name="commandes")
    objet = models.ForeignKey(ObjetCeleste, on_delete=models.CASCADE, related_name="commandes")
    cree_le = models.DateTimeField(auto_now_add=True)
    active = models.BooleanField(default=True)

    class Meta:
        ordering = ["-cree_le"]
        constraints = [
            # Au plus une commande active par appareil
            models.UniqueConstraint(
                fields=["appareil"], condition=Q(active=True), name="une_commande_active_par_appareil"
            ),
        ]

    def __str__(self):
        return f"{self.appareil} → {self.objet}" + ("" if self.active else " (terminée)")
