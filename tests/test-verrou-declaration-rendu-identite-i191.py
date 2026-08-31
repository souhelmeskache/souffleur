"""Verrou d'identité (Issue #191, découpe de #189 pt 3) : `mcp_server.py`
porte une COPIE verbatim de `ecrivain_module._valider_declaration_rendu`
(`_auteur_valider_declaration_rendu`, D-263 — mcp_server.py ne peut pas
importer ecrivain_module, cf. test-pont-mcp-auteur-d263.py § anti-LLM). Ce
test compare le CORPS des deux fonctions (source normalisée) et échoue si
l'une dérive de l'autre sans que la copie suive — jamais de dérive
silencieuse entre les deux gardes de forme.

Pur verrou de test (D-224 lane #191) : aucun changement de comportement,
la comparaison porte sur le code existant tel quel.
"""
from __future__ import annotations

import ast
import inspect
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from coderain.ecrivain_module import _valider_declaration_rendu
import mcp_server


def _corps_normalise(fn) -> str:
    """Dump AST du CORPS de la fonction (sans la docstring propre à chaque
    copie — `ecrivain_module` en porte une, `mcp_server._auteur_valider_...`
    non, cf. `mcp_server.py:2411` « Copie de
    ecrivain_module._valider_declaration_rendu » en commentaire de tête au
    lieu d'une docstring) et sans son nom (les deux copies sont nommées
    différemment par construction, D-263). Comparer l'AST plutôt que le
    texte source ignore aussi la mise en forme (indentation, retours à la
    ligne) pour ne verrouiller que la LOGIQUE."""
    tree = ast.parse(inspect.getsource(fn))
    fn_def = tree.body[0]
    assert isinstance(fn_def, ast.FunctionDef)
    body = fn_def.body
    if (body and isinstance(body[0], ast.Expr)
           and isinstance(body[0].value, ast.Constant)
           and isinstance(body[0].value.value, str)):
        body = body[1:]  # docstring éventuelle, hors comparaison
    dumps = [ast.dump(stmt, annotate_fields=False) for stmt in body]
    return "\n".join(dumps)


corps_ecrivain = _corps_normalise(_valider_declaration_rendu)
corps_mcp = _corps_normalise(mcp_server._auteur_valider_declaration_rendu)

assert corps_ecrivain == corps_mcp, (
    "ecrivain_module._valider_declaration_rendu et "
    "mcp_server._auteur_valider_declaration_rendu ont divergé — la copie "
    "verbatim (D-263) n'a pas suivi un changement fait d'un seul côté.\n"
    f"ecrivain_module:\n{corps_ecrivain!r}\n\nmcp_server:\n{corps_mcp!r}")

print("test-verrou-declaration-rendu-identite-i191: OK — les deux copies "
     "de _valider_declaration_rendu sont identiques")
