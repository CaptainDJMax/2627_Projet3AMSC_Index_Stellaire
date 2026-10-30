"""Partie 14 : réglages propres à la machine, rangés HORS de Git (comme code_pilotage.txt).

- cle_secrete.txt : clé secrète de Django (signe les sessions et les cookies). Créée toute seule
  au premier lancement si elle n'existe pas. Ne jamais la partager ni la mettre dans Git.
  (L'ancienne clé était écrite dans settings.py, donc publique sur GitHub : elle n'est plus utilisée.)
- config_locale.json : facultatif. Sans ce fichier, on reste en mode développement (comme avant).
  Exemple (voir config_locale.exemple.json) :
      {"production": true, "hotes": ["192.168.1.42", "index-stellaire.local"]}
  « production » : DEBUG coupé, fichiers statiques versionnés (fini le Ctrl+F5), erreurs dans logs/.
  « hotes » : noms ou adresses par lesquels on joint le serveur (en plus de localhost et de l'adresse
  locale du PC, ajoutées toutes seules).

Variables d'environnement prioritaires (utile sur un serveur) : INDEX_STELLAIRE_CLE,
INDEX_STELLAIRE_PRODUCTION (« 1 » ou « 0 »), INDEX_STELLAIRE_HOTES (séparés par des virgules).
"""

import json
import os
import secrets
import socket

CLES_CONNUES = {"production", "hotes"}


class ConfigInvalide(Exception):
    pass


def lire_config(base_dir):
    """Contenu vérifié de config_locale.json ({} s'il n'existe pas), complété par l'environnement."""
    chemin = base_dir / "config_locale.json"
    config = {}
    if chemin.is_file():
        try:
            config = json.loads(chemin.read_text(encoding="utf-8"))
        except (OSError, ValueError) as erreur:
            raise ConfigInvalide(f"config_locale.json illisible : {erreur}")
        if not isinstance(config, dict):
            raise ConfigInvalide("config_locale.json doit contenir un objet { ... }")
        inconnues = set(config) - CLES_CONNUES
        if inconnues:
            raise ConfigInvalide("config_locale.json : clé(s) inconnue(s) : " + ", ".join(sorted(inconnues)))
        if not isinstance(config.get("production", False), bool):
            raise ConfigInvalide("config_locale.json : « production » doit valoir true ou false")
        hotes = config.get("hotes", [])
        if not isinstance(hotes, list) or not all(isinstance(h, str) and h.strip() for h in hotes):
            raise ConfigInvalide("config_locale.json : « hotes » doit être une liste de textes")
    if os.environ.get("INDEX_STELLAIRE_PRODUCTION") in ("0", "1"):
        config["production"] = os.environ["INDEX_STELLAIRE_PRODUCTION"] == "1"
    if os.environ.get("INDEX_STELLAIRE_HOTES"):
        config["hotes"] = [h.strip() for h in os.environ["INDEX_STELLAIRE_HOTES"].split(",") if h.strip()]
    return config


def cle_secrete(base_dir):
    """Clé secrète : variable d'environnement, sinon cle_secrete.txt (créé s'il manque)."""
    cle = os.environ.get("INDEX_STELLAIRE_CLE", "").strip()
    if cle:
        return cle
    chemin = base_dir / "cle_secrete.txt"
    if chemin.is_file():
        cle = chemin.read_text(encoding="utf-8").strip()
        if len(cle) >= 50:
            return cle
    cle = secrets.token_urlsafe(64)
    chemin.write_text(cle + "\n", encoding="utf-8")
    return cle


def ip_locale():
    """Adresse du PC sur le Wi-Fi (ex. 192.168.1.42), ou None. Rien n'est envoyé : ouvrir une
    « connexion » UDP sert seulement à demander au système quelle carte réseau il utiliserait."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("192.0.2.1", 9))  # adresse réservée à la documentation, jamais jointe
            return s.getsockname()[0]
    except OSError:
        return None


def hotes_autorises(config):
    """ALLOWED_HOSTS en production : ceux de la config, plus localhost et l'adresse locale."""
    hotes = ["localhost", "127.0.0.1", *[h.strip() for h in config.get("hotes", [])]]
    ip = ip_locale()
    if ip:
        hotes.append(ip)
    return list(dict.fromkeys(hotes))  # sans doublon, dans l'ordre
