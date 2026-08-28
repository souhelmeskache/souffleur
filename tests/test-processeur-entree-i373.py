"""I-373 -- le processeur d'entrée v-min : coderain.input_processor.process
route l'entrée brute vers les 3 registres D-092 (guillemets = parole,
parenthèses = intériorité, texte nu = action) + la ligne PAROLE (trou N4,
tiret cadratin -- hypothèse documentée dans input_processor.py, non confirmée
par le vault, voir le commentaire BLOQUÉ sur l'Issue #34) + les commandes
méta (annuler/rejouer, I-237). Ce que la table ne route pas monte dans LE
PACK avec une proposition de lecture -- jamais une décision.

coderain.engine.Engine.route_input branche ce processeur sur turn() : une
commande dispatche vers son propriétaire déclaré (undo_last/swipe_generate)
SANS passer par le Director ; l'intériorité part vers le réceptacle stub
D-233b (extraire_interiorite) ; le pack (s'il y en a) monte dans le prompt du
Director sous forme de propositions ; la métrique native (part brute
transmise au Director) est émise comme un event, exactement comme les events
RPG (maybe_fold()).

Fixtures 100% synthétiques (D-109) : aucun matériau de campagne réel.
"""
import os, shutil, sys, tempfile

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1]))
from coderain import input_processor as IP
from coderain.config import load_config
from coderain.engine import Engine
from coderain.memory import Library

# ============================================================
# Partie 1 -- le routeur pur (aucun store, aucun modèle)
# ============================================================

# ---- 1) les 3 registres D-092 dans une même entrée ----
p = IP.process('"Bonjour !" (je stresse un peu) je frappe à la porte.')
by_registre = {}
for seg in p.segments:
    by_registre.setdefault(seg.registre, []).append(seg.text)
assert by_registre.get("parole") == ["Bonjour !"], by_registre
assert by_registre.get("interiorite") == ["je stresse un peu"], by_registre
assert any("je frappe à la porte" in a for a in by_registre.get("action", [])), by_registre
assert p.pack == [], p.pack
print("1) guillemets/parenthèses/texte nu routent vers les 3 registres D-092")

# ---- 2) la ligne PAROLE -- trou N4 (tiret cadratin) ----
p = IP.process("— Attends, ne pars pas !")
assert len(p.segments) == 1, p.segments
assert p.segments[0].registre == "parole", p.segments
assert p.segments[0].text == "Attends, ne pars pas !", p.segments[0].text
print("2) une ligne tiret cadratin route aussi vers 'parole' (trou N4)")

# ---- 3) commandes méta I-237, propriétaire déclaré ----
p = IP.process("annuler")
assert p.commande is not None and p.commande.proprietaire == "undo_last", p.commande
p = IP.process("Rejouer !")
assert p.commande is not None and p.commande.proprietaire == "swipe_generate", p.commande
p = IP.process("j'annule mon voyage")   # PAS une commande -- juste une action
assert p.commande is None, p.commande
print("3) commandes méta reconnues seules, propriétaire déclaré = méthode Engine")

# ---- 4) entrée ambiguë -> LE PACK avec proposition, jamais une décision ----
p = IP.process('il dit "bonjour sans fermer le guillemet')
assert len(p.pack) == 1, p.pack
assert "guillemet" in p.pack[0].proposition, p.pack[0]
assert p.pack[0].text == 'il dit "bonjour sans fermer le guillemet'
p2 = IP.process("une ( parenthèse jamais fermée")
assert len(p2.pack) == 1, p2.pack
assert "parenthèse" in p2.pack[0].proposition, p2.pack[0]
print("4) une entrée mal formée monte dans LE PACK avec une proposition, pas un routage forcé")

# ---- 5) la métrique native ----
raw = 'un peu de texte "et un bout non fermé'
p = IP.process(raw)
assert 0 < p.pack_ratio <= 1, p.pack_ratio
assert IP.classify_pack_ratio(0.9) == "ne trie pas"
assert IP.classify_pack_ratio(0.02) == "triche"
assert IP.classify_pack_ratio(0.4) == "sain"
print("5) la métrique (part brute -> Director) se calcule et se lit qualitativement")

# ============================================================
# Partie 2 -- accroché au système (Engine.turn)
# ============================================================

cfg = load_config()
cfg.generation["trinity_brain"] = False
root = os.path.join(tempfile.gettempdir(), "se_processeur_entree_i373")
if os.path.exists(root): shutil.rmtree(root)
lib = Library(root)
store = lib.store(lib.create_story("Voile", "Une cité aux portes gardées."))
engine = Engine(cfg, store)


class RecordingLLM:
    """Renvoie les textes fournis dans l'ordre ; garde chaque appel (les
    messages envoyés) pour vérifier ce qui a réellement atteint le Director."""
    def __init__(self, texts):
        self.texts = list(texts)
        self.calls = []

    def stream(self, messages, **k):
        self.calls.append(messages)
        text = self.texts.pop(0) if self.texts else "La scène continue."
        yield text

    def complete(self, *a, **k):
        return ""


engine.llm = RecordingLLM(["Vous frappez ; une servante ouvre la porte."])

# ---- 6) un tour normal : la métrique est émise comme event (maybe_fold) ----
list(engine.turn('"Bonjour !" (je stresse un peu) je frappe à la porte.'))
events = engine.maybe_fold()
metric_events = [e for e in events if e.startswith("input: ")]
assert len(metric_events) == 1, events
assert "(I-373)" in metric_events[0], metric_events
print("6) la métrique native est émise chaque tour, dans les events (comme le RPG)")

# ---- 7) extracteur des parenthèses : réceptacle stub D-233b ----
stub = store.entries(IP.STUB_INTERIORITE)
assert len(stub) == 1, stub
assert stub[0].attrs.get("dit") == "je stresse un peu", stub[0].attrs
print("7) l'intériorité part vers le réceptacle stub D-233b (support pas encore livré)")

# ---- 8) zéro fait écrit sur interprétation : aucun registre géré n'a bougé ----
for rel in ("characters.md", "locations.md", "factions.md", "items.md",
            "canon-events.md", "threads.md"):
    assert store.entries(rel) == [], (rel, store.entries(rel))
print("8) aucun registre de faits géré n'a été touché par le routage/pack")

# ---- 9) commande "annuler" tapée en clair : dispatch sans passage Director ----
engine.llm = RecordingLLM([])  # tout appel = pop sur liste vide -> "La scène continue."
calls_before = len(engine.llm.calls)
turns_before = len(store.turns())
list(engine.turn("annuler"))
assert len(engine.llm.calls) == calls_before, "annuler a appelé le modèle -- ne doit jamais passer par le Director"
assert len(store.turns()) == turns_before - 2, store.turns()  # exchange retiré
assert "annuler" not in "".join(t["text"] for t in store.turns())
print("9) 'annuler' tapé en clair dispatche vers undo_last(), zéro appel modèle")

# ---- 10) commande "rejouer" tapée en clair : régénère via swipe_generate ----
engine.llm = RecordingLLM(["Vous frappez ; personne ne répond."])
list(engine.turn('"Salut" je toque à la porte.'))
narrator_before = store.turns()[-1]["text"]
engine.llm = RecordingLLM(["Vous frappez ; un chien aboie au loin."])
list(engine.turn("rejouer"))
narrator_after = store.turns()[-1]["text"]
assert narrator_after != narrator_before, "rejouer n'a rien régénéré"
assert "rejouer" not in "".join(t["text"] for t in store.turns())
print("10) 'rejouer' tapé en clair dispatche vers swipe_generate(), régénère sans se stocker lui-même")

# ---- 11) LE PACK monte au Director avec sa proposition (objet unique) ----
engine.llm = RecordingLLM(["Le silence répond."])
list(engine.turn('il murmure "quelque chose sans fermer le guillemet'))
last_messages = engine.llm.calls[-1]
sys_content = last_messages[0]["content"]
assert "PACK D'ENTRÉE NON ROUTÉ" in sys_content, sys_content[-500:]
assert "guillemet non apparié" in sys_content, sys_content[-500:]
print("11) LE PACK monte au Director en un bloc avec sa proposition de lecture")

print("\nALL OK -- test-processeur-entree-i373.py")
