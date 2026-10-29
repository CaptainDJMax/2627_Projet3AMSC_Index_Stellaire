"""Partie 6.2 : éléments orbitaux (TLE) des satellites, pris chez CelesTrak.

Un satellite se note « sat:NUMERO » dans `identifiant_skyfield` (numéro NORAD : 25544 pour l'ISS).

- Le TLE est gardé dans donnees_skyfield/tle/<numero>.tle (dossier ignoré par Git).
- Il est retéléchargé quand il a plus de AGE_RAFRAICHISSEMENT (CelesTrak demande de ne pas
  télécharger plus souvent : ses données changent au mieux toutes les deux heures).
- Si CelesTrak ne répond pas, on garde la copie locale tant qu'elle a moins de AGE_MAX_JOURS
  (au-delà, la position de l'ISS est fausse de plusieurs degrés : mieux vaut refuser).
"""

import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from django.conf import settings

URL_CELESTRAK = "https://celestrak.org/NORAD/elements/gp.php?CATNR={numero}&FORMAT=TLE"
AGE_RAFRAICHISSEMENT_S = 6 * 3600
AGE_MAX_JOURS = 7  # âge de l'époque du TLE (pas du fichier) au-delà duquel on refuse


class TleIndisponible(ValueError):
    """Pas de TLE utilisable. Hérite de ValueError : les vues traitent déjà ce cas
    (objet ignoré sur la carte, 422 pour la trajectoire)."""


def dossier():
    defaut = Path(settings.BASE_DIR) / "donnees_skyfield" / "tle"
    return Path(getattr(settings, "DOSSIER_TLE", defaut))


def numero_de(identifiant):
    """'sat:25544' -> 25544 ; None si ce n'est pas un satellite."""
    if not identifiant.startswith("sat:"):
        return None
    try:
        return int(identifiant[4:])
    except ValueError:
        raise TleIndisponible(f"Identifiant de satellite invalide : {identifiant!r}")


def somme_controle_ok(ligne):
    """Dernier chiffre d'une ligne TLE = somme des chiffres (« - » compte 1) modulo 10."""
    if len(ligne) != 69 or not ligne[68].isdigit():
        return False
    somme = sum(int(c) if c.isdigit() else (1 if c == "-" else 0) for c in ligne[:68])
    return somme % 10 == int(ligne[68])


def lire_tle(texte, numero):
    """Texte CelesTrak (nom + 2 lignes) -> (nom, ligne1, ligne2). TleIndisponible si invalide."""
    lignes = [l.rstrip() for l in texte.strip().splitlines() if l.strip()]
    if len(lignes) == 2:
        lignes = [f"SAT {numero}"] + lignes
    if len(lignes) != 3:
        raise TleIndisponible("TLE illisible (3 lignes attendues).")
    nom, l1, l2 = lignes[0].strip(), lignes[1], lignes[2]
    if not (l1.startswith("1 ") and l2.startswith("2 ")):
        raise TleIndisponible("TLE illisible (lignes 1 et 2 attendues).")
    if not (somme_controle_ok(l1) and somme_controle_ok(l2)):
        raise TleIndisponible("TLE corrompu (somme de contrôle fausse).")
    if int(l1[2:7]) != numero or int(l2[2:7]) != numero:
        raise TleIndisponible(f"TLE d'un autre satellite que {numero}.")
    return nom, l1, l2


def epoque(ligne1):
    """Instant de référence du TLE (colonnes 19-32 de la ligne 1 : AAJJJ.JJJJJJJJ), en UTC."""
    annee = int(ligne1[18:20])
    annee += 2000 if annee < 57 else 1900
    jours = float(ligne1[20:32])
    return datetime(annee, 1, 1, tzinfo=timezone.utc).timestamp() + (jours - 1) * 86400


def _telecharger(numero):
    """Texte du TLE chez CelesTrak (remplacé dans les tests)."""
    requete = urllib.request.Request(
        URL_CELESTRAK.format(numero=numero), headers={"User-Agent": "Index-Stellaire"}
    )
    with urllib.request.urlopen(requete, timeout=10) as reponse:
        return reponse.read().decode("ascii", errors="replace")


def tle(numero):
    """{numero, nom, ligne1, ligne2, epoque (ISO UTC)} : copie locale si elle est récente,
    sinon téléchargement ; copie locale de secours si CelesTrak ne répond pas."""
    fichier = dossier() / f"{numero}.tle"
    texte = fichier.read_text(encoding="ascii") if fichier.is_file() else None
    recent = texte is not None and time.time() - fichier.stat().st_mtime < AGE_RAFRAICHISSEMENT_S

    if not recent:
        try:
            neuf = _telecharger(numero)
            lire_tle(neuf, numero)  # on n'écrase la copie locale qu'avec un TLE valide
        except (OSError, ValueError):
            pass  # réseau coupé, CelesTrak en panne, réponse invalide : on garde la copie locale
        else:
            fichier.parent.mkdir(parents=True, exist_ok=True)
            fichier.write_text(neuf.strip() + "\n", encoding="ascii")
            texte = neuf

    if texte is None:
        raise TleIndisponible(f"Aucun TLE pour le satellite {numero} (CelesTrak injoignable).")
    nom, l1, l2 = lire_tle(texte, numero)
    t_epoque = epoque(l1)
    if time.time() - t_epoque > AGE_MAX_JOURS * 86400:
        raise TleIndisponible(f"TLE du satellite {numero} trop ancien (plus de {AGE_MAX_JOURS} jours).")
    return {
        "numero": numero,
        "nom": nom,
        "ligne1": l1,
        "ligne2": l2,
        "epoque": datetime.fromtimestamp(t_epoque, timezone.utc)
        .isoformat(timespec="milliseconds").replace("+00:00", "Z"),
    }
