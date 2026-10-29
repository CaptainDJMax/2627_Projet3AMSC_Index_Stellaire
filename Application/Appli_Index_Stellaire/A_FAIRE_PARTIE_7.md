# Partie 7 : événements visibles à l'œil nu

Cette archive contient aussi toute la Partie 6 : suis d'abord `A_FAIRE_PARTIE_6.md`
(migration, `importer_contenu`), puis ce fichier. Elle remplace `partie-6-complete.zip`.

Nouveau bouton ✦ dans la barre (entre la recherche et la boussole) : le panneau « Événements ».
- **Ce soir** : heures de la nuit (Soleil à plus de 6° sous l'horizon) et la Lune et les planètes
  qu'on y voit au-dessus de 10°, avec leur hauteur maximale.
- **Les 7 prochains jours** : phases de la Lune ; rapprochements Lune-planète (5° ou moins) et
  planète-planète (3° ou moins), seulement s'ils sont observables de nuit ; essaims d'étoiles
  filantes (calendrier de l'IMO, avec « Lune gênante ») ; éclipses de Lune partielles ou totales
  si la Lune est levée ; passages de l'ISS visibles à l'œil nu et à 20° ou plus.
- Toucher une ligne : l'heure de la carte saute au meilleur moment, la vue se tourne vers
  l'événement et la fiche de l'astre s'ouvre. « Revenir à maintenant » (panneau du temps) ramène
  au direct.

## Fichiers (en plus de ceux de la Partie 6)

- NOUVEAUX : `ciel/evenements.py` (les calculs), `ciel/test_evenements.py`
- REMPLACÉS (ta version du dépôt, avec les ajouts) : `ciel/views.py` (vue `evenements`),
  `ciel/urls.py` (`/api/ciel/evenements/`), `ciel/templates/ciel/carte.html`,
  `ciel/static/ciel/carte.js`, `ciel/static/ciel/carte.css`
- CORRIGÉ : `contenu/astres/lune.json`. La Lune était en catégorie « satellite » sans identifiant
  de calcul : elle n'apparaissait pas sur la carte. Maintenant : catégorie « lune », identifiant
  `moon`. **Préviens Adrien** (c'est son dossier) : qu'il fasse `git pull` puis `importer_contenu`.

## Installer et tester

```
python manage.py importer_contenu     # « mis à jour : Lune »
python manage.py test                 # 104 tests OK attendus
python manage.py runserver 0.0.0.0:8000
```

Sur le téléphone (Ctrl+F5 ou cache vidé) : bouton ✦, puis toucher une ligne.
Vérifications faites par les tests avec des dates connues : Géminides le 14 décembre 2026,
Perséides le 13 août 2026 (calendrier IMO), éclipse partielle de Lune le 28 août 2026 vers
04 h 13 UTC, rapprochement Vénus-Jupiter le 9 juin 2026.

## Envoyer

```
git add ciel contenu appareil
git commit -m "Parties 6 et 7 : ISS, position GPS, événements visibles à l'œil nu"
git push
```
