"""Partie 14 : stockage des fichiers statiques en production.

WhiteNoise ajoute l'empreinte du contenu au nom de chaque fichier (carte.3f2a9c.js) et réécrit
les liens des CSS. La feuille de style de d3-celestial cite des images de son sélecteur de date
que nous n'utilisons pas (et n'avons pas copiées) : sans cette classe, collectstatic s'arrête.
Un lien vers un fichier absent est donc laissé tel quel au lieu de tout bloquer.
"""

from whitenoise.storage import CompressedManifestStaticFilesStorage


class StockageStatique(CompressedManifestStaticFilesStorage):
    def hashed_name(self, name, content=None, filename=None):
        try:
            return super().hashed_name(name, content, filename)
        except ValueError:
            return name
