"""D-252.2 (issue #62) : objets magiques — champs optionnels sur la classe
objet + câblage secret_lie_id vers Secret (malédiction/identification ne sont
PAS des champs de l'objet). 100% synthétique (D-109) : aucun matériau de
module réel n'entre dans cette suite."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from coderain.converter import validate_form
from coderain.converter.schemas import Manifest, Node, Partition, Record, Secret

FAIT = []


def section(nom):
    FAIT.append(nom)
    print(f"--- {nom}")


def manifest():
    return Manifest(titre="module factice", corpus_source="5e",
                    corpus_cible="5e", structures=["S1"],
                    hash_source="0" * 64,
                    date_conversion="2026-08-29T00:00:00+00:00",
                    version_convertisseur="test")


def objet(stats_extra=None, **kw):
    stats = {"description_md": "Objet d'exemple, 100% factice."}
    stats.update(stats_extra or {})
    return Record(kw.get("rid", "objet-exemple"), "objet",
                  kw.get("nom", "Objet d'exemple"), stats, [(10, 20)],
                  tags=kw.get("tags"))


# 1 -- objet ordinaire : rétrocompatibilité totale --------------------------
section("objet ordinaire : aucun champ neuf, reste valide")
r = objet()
assert r.stats_5e["description_md"]
assert "type_objet" not in r.stats_5e

# 2 -- objet magique complet -------------------------------------------------
section("objet magique complet : type, rareté, harmonisation conditionnée, "
        "activation, charges/recharge, effets_md")
r = objet({
    "type_objet": "arme",
    "rarete": "rare",
    "harmonisation": True,
    "condition_harmonisation": "par un clerc",
    "activation": "action",
    "charges": 7,
    "recharge": "1d6+4 à l'aube",
    "effets_md": "Inflige 1d6 dégâts radiants supplémentaires.",
    "persistent": ["charges"],
})
assert r.stats_5e["type_objet"] == "arme"
assert r.stats_5e["rarete"] == "rare"
assert r.stats_5e["harmonisation"] is True
assert r.stats_5e["charges"] == 7
assert r.persistent_attrs == ["charges"]  # charges rejoint persist existant

# 3 -- valeurs hors énumération refusées -------------------------------------
section("valeurs hors énumérations refusées avec message")
for bad_key, bad_val in (("type_objet", "epee"), ("rarete", "ultra-rare"),
                         ("activation", "magie")):
    try:
        objet({bad_key: bad_val})
        raise AssertionError(f"{bad_key}={bad_val!r} hors énumération accepté")
    except ValueError as e:
        assert bad_key in str(e) and bad_val in str(e), e

# 4 -- cohérences entre champs -----------------------------------------------
section("condition_harmonisation sans harmonisation=true refusé")
try:
    objet({"condition_harmonisation": "par un clerc"})
    raise AssertionError("condition_harmonisation sans harmonisation acceptée")
except ValueError as e:
    assert "harmonisation" in str(e), e

section("harmonisation non booléenne refusée")
try:
    objet({"harmonisation": "oui"})
    raise AssertionError("harmonisation non booléenne acceptée")
except ValueError:
    pass

section("recharge sans charges refusée")
try:
    objet({"recharge": "1d4 à l'aube"})
    raise AssertionError("recharge sans charges acceptée")
except ValueError as e:
    assert "charges" in str(e), e

section("charges négatives ou non entières refusées")
for bad in (-1, "sept", True):
    try:
        objet({"charges": bad})
        raise AssertionError(f"charges={bad!r} accepté")
    except ValueError:
        pass

# 5 -- champs réservés à la classe objet -------------------------------------
section("champs objets magiques réservés à la classe objet")
try:
    Record("faux-objet", "pnj", "Pas un objet",
          {"role": "allié", "description_md": "x", "type_objet": "arme"},
          [(1, 2)])
    raise AssertionError("type_objet accepté hors classe objet")
except ValueError as e:
    assert "objet" in str(e), e

# 6 -- malédiction/identification : câblage sur Secret -----------------------
section("objet maudit = objet + Secret lié, secret_lie_id résolu")
p = Partition(manifest())
p.nodes.append(Node("scene-exemple", "scene", "Scène", "Prose d'exemple.",
                    "scene", anchors=[(0, 50)]))
p.records.append(objet({
    "description_md": "Épée d'exemple +1 (face visible).",
    "type_objet": "arme",
    "rarete": "rare",
    "secret_lie_id": "secret-epee-exemple",
}, rid="epee-exemple", nom="Épée d'exemple +1"))
p.secrets.append(Secret(
    "secret-epee-exemple",
    "En vérité maudite : chuchote des ordres au porteur harmonisé.",
    "secret", ["epee-exemple"],
    {"declencheur": "harmonisation réussie 3 fois",
     "node_cible": "scene-exemple"},
    "le porteur perd le contrôle d'une action à chaque combat",
    [(60, 120)]))
errs = validate_form.validate_form(p)
assert not [e for e in errs if "secret_lie_id" in e], errs

section("secret_lie_id vers Secret inexistant refusé par le valideur")
p2 = Partition(manifest())
p2.nodes.append(Node("scene-exemple", "scene", "Scène", "Prose d'exemple.",
                     "scene", anchors=[(0, 50)]))
p2.records.append(objet({
    "description_md": "Anneau d'exemple.",
    "secret_lie_id": "secret-inexistant",
}, rid="anneau-exemple", nom="Anneau d'exemple"))
errs2 = validate_form.validate_form(p2)
assert any("secret_lie_id" in e and "secret-inexistant" in e for e in errs2), errs2

section("secret_lie_id malformé (pas un slug kebab) refusé à la construction")
try:
    objet({"secret_lie_id": "Secret Invalide"})
    raise AssertionError("secret_lie_id non-slug accepté")
except ValueError:
    pass

print(f"\nOK pconv_objets_magiques_test — {len(FAIT)} sections vertes")
