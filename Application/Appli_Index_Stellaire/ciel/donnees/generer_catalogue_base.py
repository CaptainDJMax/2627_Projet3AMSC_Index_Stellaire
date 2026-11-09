"""Génère ciel/donnees/catalogue_base.json (lancé une fois par Claude ; pas besoin de le relancer).

Sources (licence CC BY-SA 4.0, mention affichée dans les fiches) :
- étoiles : base HYG v4.1 (David Nash, astronexus/HYG-Database), magnitude <= 4,5 ;
- objets de Messier : OpenNGC (Mattia Verga), via le paquet Python pyongc ;
- Uranus et Neptune : calculées par Skyfield (éphéméride DE421), rien à télécharger.

    python ciel/donnees/generer_catalogue_base.py chemin/vers/hygdata_v41.csv
"""

import csv
import json
import sys
from pathlib import Path

MAGNITUDE_MAXI = 4.5

GREC = {
    "Alp": "α", "Bet": "β", "Gam": "γ", "Del": "δ", "Eps": "ε", "Zet": "ζ", "Eta": "η", "The": "θ",
    "Iot": "ι", "Kap": "κ", "Lam": "λ", "Mu": "μ", "Nu": "ν", "Xi": "ξ", "Omi": "ο", "Pi": "π",
    "Rho": "ρ", "Sig": "σ", "Tau": "τ", "Ups": "υ", "Phi": "φ", "Chi": "χ", "Psi": "ψ", "Ome": "ω",
}
GREC_LATIN = {
    "Alp": "Alpha", "Bet": "Beta", "Gam": "Gamma", "Del": "Delta", "Eps": "Epsilon", "Zet": "Zeta",
    "Eta": "Eta", "The": "Theta", "Iot": "Iota", "Kap": "Kappa", "Lam": "Lambda", "Mu": "Mu", "Nu": "Nu",
    "Xi": "Xi", "Omi": "Omicron", "Pi": "Pi", "Rho": "Rho", "Sig": "Sigma", "Tau": "Tau", "Ups": "Upsilon",
    "Phi": "Phi", "Chi": "Chi", "Psi": "Psi", "Ome": "Omega",
}
# Génitif latin des 88 constellations (désignations de Bayer et de Flamsteed : « Alpha Orionis »)
GENITIF = {
    "And": "Andromedae", "Ant": "Antliae", "Aps": "Apodis", "Aqr": "Aquarii", "Aql": "Aquilae", "Ara": "Arae",
    "Ari": "Arietis", "Aur": "Aurigae", "Boo": "Bootis", "Cae": "Caeli", "Cam": "Camelopardalis", "Cnc": "Cancri",
    "CVn": "Canum Venaticorum", "CMa": "Canis Majoris", "CMi": "Canis Minoris", "Cap": "Capricorni",
    "Car": "Carinae", "Cas": "Cassiopeiae", "Cen": "Centauri", "Cep": "Cephei", "Cet": "Ceti", "Cha": "Chamaeleontis",
    "Cir": "Circini", "Col": "Columbae", "Com": "Comae Berenices", "CrA": "Coronae Australis",
    "CrB": "Coronae Borealis", "Crv": "Corvi", "Crt": "Crateris", "Cru": "Crucis", "Cyg": "Cygni",
    "Del": "Delphini", "Dor": "Doradus", "Dra": "Draconis", "Equ": "Equulei", "Eri": "Eridani", "For": "Fornacis",
    "Gem": "Geminorum", "Gru": "Gruis", "Her": "Herculis", "Hor": "Horologii", "Hya": "Hydrae", "Hyi": "Hydri",
    "Ind": "Indi", "Lac": "Lacertae", "Leo": "Leonis", "LMi": "Leonis Minoris", "Lep": "Leporis", "Lib": "Librae",
    "Lup": "Lupi", "Lyn": "Lyncis", "Lyr": "Lyrae", "Men": "Mensae", "Mic": "Microscopii", "Mon": "Monocerotis",
    "Mus": "Muscae", "Nor": "Normae", "Oct": "Octantis", "Oph": "Ophiuchi", "Ori": "Orionis", "Pav": "Pavonis",
    "Peg": "Pegasi", "Per": "Persei", "Phe": "Phoenicis", "Pic": "Pictoris", "Psc": "Piscium",
    "PsA": "Piscis Austrini", "Pup": "Puppis", "Pyx": "Pyxidis", "Ret": "Reticuli", "Sge": "Sagittae",
    "Sgr": "Sagittarii", "Sco": "Scorpii", "Scl": "Sculptoris", "Sct": "Scuti", "Ser": "Serpentis",
    "Sex": "Sextantis", "Tau": "Tauri", "Tel": "Telescopii", "Tri": "Trianguli", "TrA": "Trianguli Australis",
    "Tuc": "Tucanae", "UMa": "Ursae Majoris", "UMi": "Ursae Minoris", "Vel": "Velorum", "Vir": "Virginis",
    "Vol": "Volantis", "Vul": "Vulpeculae",
}
# Noms propres : forme française quand elle diffère de la forme internationale (UAI)
NOMS_FRANCAIS = {
    "Aldebaran": "Aldébaran", "Altair": "Altaïr", "Antares": "Antarès", "Betelgeuse": "Bételgeuse",
    "Vega": "Véga", "Polaris": "Étoile polaire", "Regulus": "Régulus", "Spica": "Spica (l'Épi)",
    "Capella": "Capella (la Chèvre)", "Deneb": "Déneb", "Denebola": "Dénébola", "Fomalhaut": "Fomalhaut",
    "Electra": "Électre", "Merope": "Mérope", "Taygeta": "Taygète", "Maia": "Maïa", "Alcyone": "Alcyone",
    "Atlas": "Atlas (Pléiades)", "Rigil Kentaurus": "Alpha du Centaure", "Toliman": "Toliman",
    "Hadar": "Hadar", "Mira": "Mira", "Arcturus": "Arcturus", "Procyon": "Procyon", "Sirius": "Sirius",
}

# Objets de Messier : nom français usuel (sinon « M13 » seul) et dessin sur la carte
NOMS_MESSIER = {
    1: "nébuleuse du Crabe", 8: "nébuleuse de la Lagune", 11: "amas du Canard sauvage", 13: "amas d'Hercule",
    16: "nébuleuse de l'Aigle", 17: "nébuleuse Oméga", 20: "nébuleuse Trifide", 24: "nuage stellaire du Sagittaire",
    27: "nébuleuse de l'Haltère", 31: "galaxie d'Andromède", 33: "galaxie du Triangle", 42: "nébuleuse d'Orion",
    43: "nébuleuse de De Mairan", 44: "amas de la Ruche", 45: "Pléiades", 51: "galaxie du Tourbillon",
    57: "nébuleuse de la Lyre", 63: "galaxie du Tournesol", 64: "galaxie de l'Œil noir", 76: "petite nébuleuse de l'Haltère",
    81: "galaxie de Bode", 82: "galaxie du Cigare", 83: "galaxie du Moulinet austral", 97: "nébuleuse du Hibou",
    101: "galaxie du Moulinet", 102: "galaxie du Fuseau", 104: "galaxie du Sombrero", 6: "amas du Papillon", 7: "amas de Ptolémée",
}
TYPES_OPENNGC = {  # type OpenNGC -> (catégorie, teinte du voile, mot français)
    "Galaxy": ("ciel_profond", "galaxie", "galaxie"), "Gx": ("ciel_profond", "galaxie", "galaxie"),
    "Globular Cluster": ("amas", None, "amas globulaire"), "Open Cluster": ("amas", None, "amas ouvert"),
    "Star cluster + Nebula": ("ciel_profond", "nebuleuse", "amas et nébuleuse"),
    "Association of stars": ("amas", None, "nuage d'étoiles"), "Object of other/unknown type": ("amas", None, "astérisme"),
    "HII Ionized region": ("ciel_profond", "nebuleuse", "nébuleuse"), "Nebula": ("ciel_profond", "nebuleuse", "nébuleuse"),
    "Planetary Nebula": ("ciel_profond", "nebuleuse", "nébuleuse planétaire"),
    "Supernova remnant": ("ciel_profond", "nebuleuse", "rémanent de supernova"),
    "Reflection Nebula": ("ciel_profond", "nebuleuse", "nébuleuse"),
    "Star cloud": ("amas", None, "nuage d'étoiles"), "Asterism": ("amas", None, "astérisme"),
    "Double star": ("amas", None, "étoile double"),
}


EXPOSANTS = str.maketrans("0123456789", "⁰¹²³⁴⁵⁶⁷⁸⁹")


def designation(r):
    """« α Orionis » (Bayer), sinon « 58 Orionis » (Flamsteed), sinon « HD 39801 »."""
    con = GENITIF.get(r["con"], r["con"])
    if r["bayer"]:
        lettre, _, indice = r["bayer"].partition("-")
        return f"{GREC[lettre]}{indice.translate(EXPOSANTS)} {con}"
    if r["flam"]:
        return f"{r['flam']} {con}"
    return f"HD {r['hd']}" if r["hd"] else f"HIP {r['hip']}"


def titres_wikipedia_etoile(r, nom):
    """Titres à essayer sur fr.wikipedia.org, du plus sûr au moins sûr (le résumé est ensuite vérifié :
    il doit parler d'une étoile)."""
    titres = []
    con = GENITIF.get(r["con"])
    if r["bayer"] and con:
        lettre, _, indice = r["bayer"].partition("-")
        titres.append(f"{GREC_LATIN[lettre]}{indice} {con}")  # « Alpha Orionis », « Alpha2 Librae »
    if r["flam"] and con:
        titres.append(f"{r['flam']} {con}")
    if r["proper"]:
        titres += [f"{nom} (étoile)", nom]
    if not titres and r["hd"]:
        titres.append(f"HD {r['hd']}")
    return titres


def etoiles(chemin_hyg):
    lignes = [r for r in csv.DictReader(open(chemin_hyg, encoding="utf-8"))
              if r["hip"] and r["mag"] and float(r["mag"]) <= MAGNITUDE_MAXI]
    resultat, vus = [], set()
    for r in sorted(lignes, key=lambda r: float(r["mag"])):
        nom_propre = NOMS_FRANCAIS.get(r["proper"], r["proper"])
        desig = designation(r)
        nom = nom_propre or desig
        if nom in vus:
            nom = f"{nom} (HIP {r['hip']})"
        vus.add(nom)
        resultat.append({
            "cle": f"hip:{r['hip']}", "nom": nom, "designation": desig if nom_propre else "",
            "categorie": "etoile", "identifiant": f"hip:{r['hip']}", "magnitude": round(float(r["mag"]), 2),
            "constellation": r["con"], "type": r["spect"],
            "wikipedia": titres_wikipedia_etoile(r, nom_propre),
            "credit_donnees": "Base HYG v4.1 (astronexus), CC BY-SA 4.0",
        })
    return resultat


def nom_catalogue(nom):
    """« NGC0224 » -> « NGC 224 », « Mel022 » -> « Mel 22 »."""
    import re

    m = re.match(r"^([A-Za-z]+)0*(\d+)(.*)$", nom)
    return f"{m.group(1)} {m.group(2)}{m.group(3)}" if m else nom


def messier():
    from pyongc import ongc

    resultat = []
    for n in range(1, 111):
        # M102 : OpenNGC le confond avec M101 (même galaxie, NGC 5457) ; on retient l'identification
        # la plus courante, NGC 5866 (galaxie du Fuseau)
        o = ongc.get("NGC5866" if n == 102 else f"M{n}")
        if o is None:
            raise SystemExit(f"M{n} introuvable dans OpenNGC")
        ra = round(float(o.ra.split(":")[0]) * 15 + float(o.ra.split(":")[1]) / 4 + float(o.ra.split(":")[2]) / 240, 4)
        signe = -1 if o.dec.strip().startswith("-") else 1
        d, m, s = (abs(float(x)) for x in o.dec.strip().lstrip("+-").split(":"))
        dec = round(signe * (d + m / 60 + s / 3600), 4)
        categorie, teinte, mot = TYPES_OPENNGC.get(o.type, ("ciel_profond", "galaxie", o.type.lower()))
        grand, petit, angle = o.dimensions
        grand_deg = round((grand or 5) / 60, 3)
        petit_deg = round((petit or grand or 5) / 60, 3)
        if categorie == "amas":
            forme = {"type": "amas", "diametre": max(grand_deg, 0.1)}
        else:
            forme = {"type": "ellipse", "grand_axe": max(grand_deg, 0.05), "petit_axe": max(petit_deg, 0.05),
                     "angle": int(angle or 0), "teinte": teinte}
        mags = o.magnitudes
        magnitude = mags[1] if mags[1] is not None else mags[0]
        nom_fr = NOMS_MESSIER.get(n)
        nom = f"M{n} · {nom_fr[0].upper() + nom_fr[1:]}" if nom_fr else f"M{n}"
        resultat.append({
            "cle": f"M{n}", "nom": nom, "designation": f"M{n}" + ("" if o.name.startswith("M") else f", {nom_catalogue(o.name)}"),
            "categorie": categorie, "identifiant": f"radec:{ra},{dec}",
            "magnitude": round(magnitude, 1) if magnitude is not None else None,
            "constellation": o.constellation, "type": mot, "forme": forme,
            "wikipedia": [f"M{n}", f"Messier {n}"] + ([nom_fr[0].upper() + nom_fr[1:]] if nom_fr else []),
            "credit_donnees": "OpenNGC (Mattia Verga), CC BY-SA 4.0",
        })
    return resultat


# Toutes les planètes, plus Pluton : présentes même si les fiches de contenu/ ne sont pas importées.
# Une fiche écrite (même identifiant) reste prioritaire, comme pour les étoiles.
PLANETES = [
    ("mercure", "Mercure", "mercury", "planète tellurique", "Mercure (planète)", None),
    ("venus", "Vénus", "venus", "planète tellurique", "Vénus (planète)", None),
    ("mars", "Mars", "mars barycenter", "planète tellurique", "Mars (planète)", None),
    ("jupiter", "Jupiter", "jupiter barycenter", "planète géante gazeuse", "Jupiter (planète)", None),
    ("saturne", "Saturne", "saturn barycenter", "planète géante gazeuse", "Saturne (planète)", None),
    ("uranus", "Uranus", "uranus barycenter", "planète géante de glaces", "Uranus (planète)", None),
    ("neptune", "Neptune", "neptune barycenter", "planète géante de glaces", "Neptune (planète)", None),
    # Skyfield ne calcule pas la magnitude de Pluton : valeur moyenne du catalogue
    ("pluton", "Pluton", "pluto barycenter", "planète naine", "Pluton (planète naine)", 14.4),
]


def planetes():
    return [
        {"cle": f"planete:{cle}", "nom": nom, "designation": "", "categorie": "planete", "identifiant": ident,
         "magnitude": magnitude, "constellation": "", "type": genre, "wikipedia": [titre], "credit_donnees": ""}
        for cle, nom, ident, genre, titre, magnitude in PLANETES
    ]


if __name__ == "__main__":
    donnees = {"version": 1, "astres": planetes() + messier() + etoiles(sys.argv[1])}
    sortie = Path(__file__).with_name("catalogue_base.json")
    sortie.write_text(json.dumps(donnees, ensure_ascii=False, indent=0) + "\n", encoding="utf-8")
    print(sortie, len(donnees["astres"]), "astres")
