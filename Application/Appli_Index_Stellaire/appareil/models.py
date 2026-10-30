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
    # Partie 8.5 (F22) : visite guidée. Liste d'étapes {objet_id, ra, dec, nom, identifiant,
    # duree_s} suivies l'une après l'autre à partir de debut_programme. Avant le début, le bras
    # vise déjà la première étape ; après la fin, il reste sur la dernière. objet/ra/dec ci-dessus
    # gardent la première étape (contrainte « objet ou coordonnées »).
    programme = models.JSONField(null=True, blank=True)
    debut_programme = models.DateTimeField(null=True, blank=True)
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

    # --- Partie 8.5 : la visite guidée ---------------------------------------------------------

    def etapes_datees(self):
        """[(numero à partir de 0, étape, début, fin)] ; fin None pour la dernière (elle dure)."""
        resultat, debut = [], self.debut_programme
        for i, etape in enumerate(self.programme or []):
            fin = debut + timedelta(seconds=etape["duree_s"]) if i < len(self.programme) - 1 else None
            resultat.append((i, etape, debut, fin))
            debut = debut + timedelta(seconds=etape["duree_s"])
        return resultat

    def etape_a(self, quand=None):
        """(numero, étape, début, fin) de la visite à l'instant `quand` (datetime), ou None si la
        commande n'est pas une visite. Avant le début : la première étape ; après : la dernière."""
        if not self.programme:
            return None
        quand = quand or timezone.now()
        etapes = self.etapes_datees()
        for e in etapes:
            if e[3] is None or quand < e[3]:
                return e
        return etapes[-1]

    def _cible(self, quand=None):
        """{identifiant, nom, objet_id, coordonnees} de ce que le bras doit viser à cet instant."""
        e = self.etape_a(quand)
        if e is not None:
            etape = e[1]
            point = etape["objet_id"] is None
            return {
                "identifiant": etape["identifiant"],
                "nom": etape["nom"],
                "objet_id": etape["objet_id"],
                "coordonnees": {"ra": etape["ra"], "dec": etape["dec"]} if point else None,
            }
        if self.objet is not None:
            return {"identifiant": self.objet.identifiant_skyfield, "nom": self.objet.nom,
                    "objet_id": self.objet.id, "coordonnees": None}
        return {"identifiant": f"radec:{self.ra},{self.dec}", "nom": self.nom_cible or NOM_POINT_DU_CIEL,
                "objet_id": None, "coordonnees": {"ra": self.ra, "dec": self.dec}}

    def identifiant_a(self, quand=None):
        """Ce que ciel.astro sait calculer : celui de l'objet, ou « radec:RA,DEC » pour un point."""
        return self._cible(quand)["identifiant"]

    @property
    def identifiant(self):
        return self.identifiant_a()

    @property
    def nom(self):
        return self._cible()["nom"]

    def coordonnees_a(self, quand=None):
        """{ra, dec} pour un point du ciel, None pour un objet de la base."""
        return self._cible(quand)["coordonnees"]

    @property
    def coordonnees(self):
        return self.coordonnees_a()

    def resume_objet(self, quand=None):
        """Le champ « objet » des réponses : id None pour un point du ciel (8.4)."""
        c = self._cible(quand)
        return {"id": c["objet_id"], "nom": c["nom"]}

    def __str__(self):
        return f"{self.appareil} → {self.nom}" + ("" if self.active else " (terminée)")
