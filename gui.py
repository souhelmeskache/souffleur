"""Coderain — Windows 2000-style Tkinter GUI (Markdown-backed memory).

Régime SECONDAIRE (D-267) — flexibilité locale/API ; le produit joué passe
par le chemin MCP/forfait, pas par ici.

Tabs:
  Chat      play the story; generation runs on a worker thread (UI stays live)
  Settings  active profile, model, API key, generation + memory params
  Memory    edit the story's Markdown memory files on the fly

Run:  py gui.py
"""
from __future__ import annotations

import json
import os
import queue
import sys
import threading


def _ensure_tcl() -> None:
    """Point Tk at its runtime. In a venv the Tcl auto-locator often looks in the
    wrong place (\\lib\\tcl8.6 instead of \\tcl\\tcl8.6), so set the env vars from
    the base install ourselves if they aren't already set."""
    if os.environ.get("TCL_LIBRARY"):
        return
    from pathlib import Path
    tcl_root = Path(sys.base_prefix) / "tcl"
    if not tcl_root.is_dir():
        return
    for d in tcl_root.iterdir():
        if d.name.startswith("tcl8"):
            os.environ.setdefault("TCL_LIBRARY", str(d))
        elif d.name.startswith("tk8"):
            os.environ.setdefault("TK_LIBRARY", str(d))


_ensure_tcl()

import tkinter as tk  # noqa: E402
from tkinter import messagebox, ttk  # noqa: E402

from coderain.config import (  # noqa: E402
    ROOT, load_config, save_yaml, read_env, write_env,
)
from coderain import models as models_mod  # noqa: E402
from coderain.features import pro_module  # noqa: E402
rpg_mod = pro_module("rpg")  # None on a free install  # noqa: E402
from coderain.templates import DEFAULT_PREMISE  # noqa: E402
from coderain.engine import Engine  # noqa: E402
from coderain.llm import LLM  # noqa: E402
from coderain.generator import ScenarioSpec, generate_scenario  # noqa: E402
from coderain.memory import (  # noqa: E402
    Entry, Library, MemoryStore, EDITABLE_FILES, RULE_FILES,
)
from tkinter import filedialog, simpledialog  # noqa: E402

# --- Windows 2000 palette / fonts (chrome: tabs, settings, buttons) ---
BG = "#c0c0c0"
WHITE = "#ffffff"
NAVY = "#000080"
UI_FONT = ("Tahoma", 8)
STORY_FONT = ("Tahoma", 10)
EDIT_FONT = ("Consolas", 10)

# --- "book on a terminal" theme for the text windows (Matrix: black + green) ---
# The reading pane renders narration top-down like a page; the player's input sits
# at the bottom-left behind a prompt, as if typed at a console.
TERM_BG = "#050705"          # near-black page
TERM_NARR = "#3ce070"        # narration — calm phosphor green, easy on long reads
TERM_PLAYER = "#b9ffc6"      # the player's own lines — brighter, like a live prompt
TERM_SYS = "#2f8a4d"         # system / mechanics notes — dim green
TERM_PROMPT = "#7CFC66"      # the ">" caret/prompt glyph
TERM_SEL = "#12351f"         # selection background
BOOK_FONT = ("Consolas", 13)     # monospace column = the "book" body
BOOK_ITALIC = ("Consolas", 11, "italic")
PROMPT_FONT = ("Consolas", 13, "bold")


class App(tk.Tk):
    def __init__(self, root=None):
        super().__init__()
        self.title("Coderain")
        self.geometry("920x640")
        self.minsize(820, 560)   # keep the console buttons + settings from crushing
        self.configure(bg=BG)
        self.option_add("*Font", UI_FONT)

        self.cfg = load_config()
        self.lib = Library(root or ROOT)
        self.lib.scenarios.ensure_default()
        self.store: MemoryStore | None = None
        self.slug: str | None = None
        self.engine: Engine | None = None
        self.generating = False
        self.sheet_visible = False        # pinned character-sheet side panel toggle
        self._opening_attempted = False   # a blank save tried (and may have failed)
        self._note_job = None             # after() id of the generating animation
        self.msg_queue: queue.Queue = queue.Queue()

        self._init_style()
        self._build_menubar()
        nb = ttk.Notebook(self)
        nb.pack(fill="both", expand=True, padx=4, pady=4)
        self.tab_chat = tk.Frame(nb, bg=BG)
        self.tab_settings = tk.Frame(nb, bg=BG)
        self.tab_memory = tk.Frame(nb, bg=BG)
        self.tab_editor = tk.Frame(nb, bg=BG)
        nb.add(self.tab_chat, text="  Chat  ")
        nb.add(self.tab_settings, text="  Settings  ")
        nb.add(self.tab_memory, text="  Memory  ")
        nb.add(self.tab_editor, text="  Editor  ")
        self._build_chat()
        self._build_settings()
        self._build_memory()
        self._build_editor()

        self._load_stories_list()
        self._ensure_story()
        self.after(50, self._drain_queue)

    # ---------- styling ----------
    def _init_style(self):
        style = ttk.Style()
        try:
            style.theme_use("classic")
        except tk.TclError:
            pass
        style.configure(".", background=BG, font=UI_FONT)
        style.configure("TNotebook", background=BG, borderwidth=1)
        style.configure("TNotebook.Tab", background=BG, padding=(6, 2))
        style.map("TNotebook.Tab", background=[("selected", BG)])

    def _group(self, parent, text):
        return tk.LabelFrame(parent, text=text, bg=BG, font=UI_FONT,
                             relief="groove", bd=2, padx=6, pady=4)

    def _button(self, parent, text, cmd, width=10):
        return tk.Button(parent, text=text, command=cmd, width=width,
                         relief="raised", bd=2, bg=BG, activebackground=BG,
                         font=UI_FONT)

    def _place_dialog(self, dlg):
        """Open a Toplevel at the mouse pointer (clamped to the screen) instead of
        the window manager's default top-left drift."""
        if not dlg.winfo_exists():   # closed before the after_idle callback fired
            return
        dlg.update_idletasks()
        w = max(dlg.winfo_reqwidth(), dlg.winfo_width())
        h = max(dlg.winfo_reqheight(), dlg.winfo_height())
        x = max(0, min(self.winfo_pointerx() - 24,
                       dlg.winfo_screenwidth() - w))
        y = max(0, min(self.winfo_pointery() - 12,
                       dlg.winfo_screenheight() - h))
        dlg.geometry(f"+{x}+{y}")

    def _talk_dialog(self):
        """Private companion side-chat (Wave 3): its own little window, its own
        worker thread — never blocks the UI, never touches the transcript."""
        if self.store is None or self.engine is None:
            return
        comps = self.engine.companions()
        if not comps:
            messagebox.showinfo(
                "Companion chat",
                "No companions yet. Mark one with `companion: true` on its "
                "characters.md entry, or let the story recruit one.")
            return
        dlg = tk.Toplevel(self)
        dlg.title("Companion side-chat (private — not part of the story)")
        dlg.configure(bg=BG)
        dlg.transient(self)
        top = tk.Frame(dlg, bg=BG)
        top.pack(fill="x", padx=8, pady=(8, 2))
        tk.Label(top, text="Talk to:", bg=BG).pack(side="left")
        who_var = tk.StringVar(value=comps[0])
        ttk.Combobox(top, textvariable=who_var, state="readonly",
                     values=comps, width=22).pack(side="left", padx=6)
        log = tk.Text(dlg, width=64, height=18, font=BOOK_FONT, bg=TERM_BG,
                      fg=TERM_NARR, insertbackground=TERM_PROMPT, wrap="word",
                      relief="sunken", bd=2, state="disabled")
        log.pack(fill="both", expand=True, padx=8, pady=4)
        log.tag_configure("you", foreground=TERM_PLAYER)
        row = tk.Frame(dlg, bg=BG)
        row.pack(fill="x", padx=8, pady=(0, 8))
        entry = tk.Entry(row, relief="sunken", bd=2, font=BOOK_FONT, bg=TERM_BG,
                         fg=TERM_PLAYER, insertbackground=TERM_PROMPT)
        entry.pack(side="left", fill="x", expand=True)
        busy = {"on": False}

        def put(text, tag=None):
            log.configure(state="normal")
            log.insert("end", text, tag or ())
            log.see("end")
            log.configure(state="disabled")

        def send(_evt=None):
            msg = entry.get().strip()
            if not msg or busy["on"]:
                return
            if self.generating:
                put("\n(wait for the current story turn to finish)\n")
                return
            # Pin the engine: switching saves mid-chat must not retarget the
            # conversation (and its log) to the newly opened save.
            eng = self.engine
            entry.delete(0, "end")
            who = who_var.get()
            put(f"\nYou → {who}: {msg}\n", "you")
            put(f"{who}: ")
            busy["on"] = True

            def ui(text):
                # Worker-side Tk access is defensive only: the dialog may be
                # torn down mid-stream, which raises instead of returning False.
                try:
                    if dlg.winfo_exists():
                        dlg.after(0, put, text)
                except (tk.TclError, RuntimeError):
                    pass

            def worker():
                try:
                    for piece in eng.companion_chat(who, msg):
                        ui(piece)
                except Exception as e:  # noqa: BLE001
                    ui(f"[error: {e}]")
                finally:
                    busy["on"] = False
                    ui("\n")
            threading.Thread(target=worker, daemon=True).start()

        entry.bind("<Return>", send)
        self._button(row, "Send", send, width=8).pack(side="left", padx=(6, 0))
        put("(This talk stays between you two. The story only ever hears a "
            "faint echo of it.)\n")
        entry.focus_set()
        self.after_idle(lambda: self._place_dialog(dlg))

    def _show_context_hints(self):
        """Small read-only dialog: context windows of popular hosted models (the
        visual the PWA will render from the same coderain.models data)."""
        dlg = tk.Toplevel(self)
        dlg.title("Model context sizes")
        dlg.configure(bg=BG)
        dlg.transient(self)
        body = (models_mod.context_hint_lines() + [""]
                + models_mod.platform_comparison_lines())
        txt = tk.Text(dlg, width=80, height=min(len(body) + 1, 38),
                      font=("Consolas", 9), relief="sunken", bd=2,
                      bg="white", fg="black")
        txt.pack(padx=10, pady=(10, 4))
        txt.insert("1.0", "\n".join(body))
        txt.configure(state="disabled")
        self._button(dlg, "Close", dlg.destroy, width=10).pack(pady=(0, 10))
        self.after_idle(lambda: self._place_dialog(dlg))

    def _build_menubar(self):
        bar = tk.Menu(self)
        m = tk.Menu(bar, tearoff=0)
        m.add_command(label="New save...", command=self.new_story_dialog)
        m.add_command(label="Duplicate this save", command=self._duplicate_save)
        m.add_command(label="Branch from turn...", command=self._branch_save)
        m.add_command(label="Rename this save...", command=self._rename_save)
        m.add_command(label="Delete a save...", command=self._delete_save)
        m.add_separator()
        m.add_command(label="Export this save...", command=self._export_save)
        m.add_command(label="Import a save...", command=self._import_save)
        m.add_separator()
        m.add_command(label="Exit", command=self.destroy)
        bar.add_cascade(label="Save", menu=m)

        sc = tk.Menu(bar, tearoff=0)
        sc.add_command(label="New scenario (world)...",
                       command=self._new_scenario_dialog)
        sc.add_command(label="Generate scenario (AI)...",
                       command=self._generate_scenario_dialog)
        sc.add_command(label="Delete scenario...",
                       command=self._delete_scenario_dialog)
        bar.add_cascade(label="Scenario", menu=sc)
        self.config(menu=bar)

    # ---------- CHAT TAB ----------
    def _build_chat(self):
        top = tk.Frame(self.tab_chat, bg=BG)
        top.pack(fill="x", padx=4, pady=4)
        tk.Label(top, text="Save:", bg=BG).pack(side="left")
        self.story_var = tk.StringVar()
        self.story_combo = ttk.Combobox(top, textvariable=self.story_var,
                                        state="readonly", width=40)
        self.story_combo.pack(side="left", padx=4)
        self.story_combo.bind("<<ComboboxSelected>>", self._on_story_select)
        self._button(top, "New", self.new_story_dialog, width=6).pack(side="left")
        self.rpg_btn_var = tk.StringVar(value="RPG: off")
        self.rpg_btn = tk.Button(top, textvariable=self.rpg_btn_var,
                                 command=self._toggle_rpg, width=9, relief="raised",
                                 bd=2, bg=BG, activebackground=BG, font=UI_FONT)
        self.rpg_btn.pack(side="left", padx=(8, 0))
        self._button(top, "Sheet", self._show_sheet, width=6).pack(side="left",
                                                                    padx=(2, 0))
        self._button(top, "Talk", self._talk_dialog, width=6).pack(side="left",
                                                                   padx=(2, 0))

        # --- the page: a reading column + an optional pinned sheet panel ---
        midwrap = tk.Frame(self.tab_chat, bg=BG)
        midwrap.pack(fill="both", expand=True, padx=4, pady=2)
        # Pinned character sheet (item: NOT a separate window). Toggled by the Sheet
        # button; sits to the RIGHT of the reading column, one stat per line.
        self.sheet_panel = tk.Frame(midwrap, bg=TERM_BG, bd=2, relief="sunken")
        tk.Label(self.sheet_panel, text="— CHARACTER —", bg=TERM_BG, fg=TERM_SYS,
                 font=UI_FONT).pack(fill="x", pady=(6, 2))
        self._sheet_text = tk.Text(self.sheet_panel, wrap="none", width=24,
                                   bg=TERM_BG, fg=TERM_NARR, relief="flat", bd=0,
                                   font=("Consolas", 10), padx=10, pady=6,
                                   state="disabled")
        self._sheet_text.pack(fill="both", expand=True)
        mid = tk.Frame(midwrap, bg=TERM_BG, bd=2, relief="sunken")
        mid.pack(side="left", fill="both", expand=True)
        self._mid_frame = mid   # sheet panel packs BEFORE this to claim its width
        self.chat = tk.Text(mid, wrap="word", bg=TERM_BG, fg=TERM_NARR,
                            relief="flat", bd=0, font=BOOK_FONT,
                            state="disabled", padx=44, pady=26, spacing2=3,
                            insertbackground=TERM_NARR,
                            selectbackground=TERM_SEL, selectforeground=TERM_PLAYER)
        sb = tk.Scrollbar(mid, command=self.chat.yview, bg=TERM_BG,
                          troughcolor="#0c120c", activebackground=TERM_SYS,
                          bd=0, relief="flat", width=12)
        self.chat.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.chat.pack(side="left", fill="both", expand=True)
        # narration = the book body: generous line/paragraph spacing + a text column
        self.chat.tag_configure("narration", foreground=TERM_NARR,
                                lmargin1=8, lmargin2=8, rmargin=8,
                                spacing1=2, spacing3=12)
        # player = a live console line, brighter, behind its "> " prompt
        self.chat.tag_configure("player", foreground=TERM_PLAYER, font=PROMPT_FONT,
                                lmargin1=8, lmargin2=30, spacing1=10, spacing3=4)
        self.chat.tag_configure("system", foreground=TERM_SYS, font=BOOK_ITALIC,
                                lmargin1=8, lmargin2=8, spacing1=2, spacing3=2)

        # --- the console: a prompt glyph + the player's input line, bottom-left ---
        # The button column is packed BEFORE the input so a narrow window squeezes
        # the input, never the buttons (they used to crush together).
        bottom = tk.Frame(self.tab_chat, bg=TERM_BG, bd=2, relief="sunken")
        bottom.pack(fill="x", padx=4, pady=(0, 4))
        col = tk.Frame(bottom, bg=TERM_BG)
        col.pack(side="right", padx=6, pady=4)
        self.send_btn = self._button(col, "Send", self._on_send, width=8)
        self.send_btn.pack(fill="x")
        self._button(col, "Retry", self._on_retry, width=8).pack(fill="x", pady=(3, 0))
        self._button(col, "Undo", self._on_undo, width=8).pack(fill="x", pady=(3, 0))
        tk.Label(bottom, text=">", bg=TERM_BG, fg=TERM_PROMPT, font=PROMPT_FONT
                 ).pack(side="left", padx=(10, 4), anchor="n", pady=6)
        self.input = tk.Text(bottom, height=3, wrap="word", bg=TERM_BG,
                             fg=TERM_PLAYER, relief="flat", bd=0, font=BOOK_FONT,
                             insertbackground=TERM_PROMPT, insertwidth=2,
                             selectbackground=TERM_SEL, selectforeground=TERM_PLAYER,
                             padx=2, pady=6)
        self.input.pack(side="left", fill="both", expand=True)
        self.input.bind("<Return>", self._on_enter)

    def _refresh_rpg_btn(self):
        on = self.store is not None and self.store.rpg_enabled()
        self.rpg_btn_var.set("RPG: on" if on else "RPG: off")

    def _toggle_rpg(self):
        if self.store is None or self.generating:
            return
        state = self.store.rpg_state()
        state["enabled"] = not state.get("enabled", False)
        self.store.set_rpg_state(state)
        self._refresh_rpg_btn()
        self._refresh_sheet_panel()
        self._append(f"\n· RPG mechanics: {'ON' if state['enabled'] else 'OFF'}\n",
                     "system")

    def _show_sheet(self):
        """Toggle the pinned character-sheet side panel (right of the reading
        column, one value per line)."""
        if self.store is None:
            return
        if self.sheet_visible:
            self.sheet_panel.pack_forget()
            self.sheet_visible = False
            return
        if not self.store.rpg_enabled():
            messagebox.showinfo("Character sheet",
                                "RPG mechanics are off (click RPG to enable).")
            return
        # before=: put the panel EARLIER in the pack order than the expanding chat
        # column, so the packer allocates the panel's width first (packed after, it
        # gets whatever the chat left over — i.e. crushed).
        self.sheet_panel.pack(side="right", fill="y", padx=(4, 0),
                              before=self._mid_frame)
        self.sheet_visible = True
        self._refresh_sheet_panel()

    def _refresh_sheet_panel(self):
        """Re-render the pinned sheet in place (after each turn / undo / toggle /
        story switch). No-op while hidden."""
        if not self.sheet_visible or self.store is None:
            return
        if self.store.rpg_enabled():
            body = "(Coderain Pro required)" if rpg_mod is None                 else rpg_mod.render_sheet_lines(self.store.rpg_state(),
                                              self.store.world_state())
        else:
            body = "RPG mechanics are off\nfor this save.\n\n(click RPG to enable)"
        self._sheet_text.configure(state="normal")
        self._sheet_text.delete("1.0", "end")
        self._sheet_text.insert("1.0", body)
        self._sheet_text.configure(state="disabled")

    def _append(self, text, tag):
        self.chat.configure(state="normal")
        self.chat.insert("end", text, tag)
        self.chat.see("end")
        self.chat.configure(state="disabled")

    def _on_enter(self, event):
        if event.state & 0x0001:  # Shift held -> newline
            return
        self._on_send()
        return "break"

    # --- transcript marks: where the current exchange / response begins, so retry
    # and undo can REMOVE the superseded text instead of stacking below it. ---
    def _set_mark(self, name):
        self.chat.mark_set(name, "end-1c")
        self.chat.mark_gravity(name, "left")
        self._marks_slug = self.slug

    def _clear_from_mark(self, name) -> bool:
        """Delete everything from `name` to the end of the chat. False when the mark
        doesn't belong to this story's widget content (e.g. after a story switch)."""
        if getattr(self, "_marks_slug", None) != self.slug:
            return False
        try:
            idx = self.chat.index(name)
        except tk.TclError:
            return False
        self.chat.configure(state="normal")
        self.chat.delete(idx, "end")
        self.chat.configure(state="disabled")
        return True

    def _on_send(self):
        if self.generating or self.engine is None:
            return
        text = self.input.get("1.0", "end").strip()
        if not text:
            return
        self.input.delete("1.0", "end")
        self._set_mark("turn_start")            # undo removes from here
        self._append(f"\n> {text}\n\n", "player")
        self._set_mark("resp_start")            # retry removes from here
        self._start_generation(lambda eng: eng.turn(text, on_stage=self._stage_cb),
                               fold_after=True, note="generating")

    def _on_retry(self):
        if self.generating or self.engine is None:
            return
        turns = self.store.turns()
        if not turns or (len(turns) == 1 and turns[0]["role"] == "narrator"):
            # Blank save (failed opening) or opening-only: regenerate the opening
            # on a clean page.
            if turns:
                self.store.drop_last_turns(1)
            self.chat.configure(state="normal")
            self.chat.delete("1.0", "end")
            self.chat.configure(state="disabled")
            self._start_generation(lambda eng: eng.opening(on_stage=self._stage_cb),
                                   note="retrying the opening")
            return
        if turns[-1]["role"] == "narrator" and len(turns) >= 2:
            last_player = turns[-2]["text"]
            self.store.drop_last_turns(2)
        elif turns[-1]["role"] == "player":
            # orphan player turn (previous generation produced nothing) — reuse it
            last_player = turns[-1]["text"]
            self.store.drop_last_turns(1)
        else:
            messagebox.showinfo("Retry", "Nothing to retry yet.")
            return
        self.engine.restore_pre_turn_rpg()  # roll back the retried turn's mechanics
        # Wipe the superseded response (and its fold/mechanics lines) from the page.
        self._clear_from_mark("resp_start")
        self._start_generation(
            lambda eng: eng.turn(last_player, on_stage=self._stage_cb),
            fold_after=True, note="retrying")

    def _stage_cb(self, msg):
        """Trinity stage marker -> system line (thread-safe via the queue)."""
        self.msg_queue.put(("system", f"· {msg}...\n"))

    def _on_undo(self):
        if self.generating or self.engine is None:
            return
        if self.engine.undo_last():
            if not self._clear_from_mark("turn_start"):
                # Exchange predates this session's widget content — note it instead.
                self._append("\n· undone — the last exchange was removed.\n",
                             "system")
            self._refresh_sheet_panel()   # deltas rolled back; refresh if open
        else:
            messagebox.showinfo("Undo", "Nothing to undo yet.")

    # --- "reply is being generated" note: animated dots, removed when the first
    # prose chunk lands (or the run ends). ---
    def _note_show(self, text):
        self._note_clear()
        self._note_base = f"· {text}"
        self._note_dots = 0
        self.chat.configure(state="normal")
        self.chat.insert("end", "\n" + self._note_base, ("system", "gen_note"))
        self.chat.see("end")
        self.chat.configure(state="disabled")
        self._note_job = self.after(400, self._animate_note)

    def _delete_note_ranges(self):
        """Delete EVERY gen_note-tagged region (tag_ranges returns start/end pairs;
        deleting only the first pair would orphan any stray extra note)."""
        r = self.chat.tag_ranges("gen_note")
        if not r:
            return False
        self.chat.configure(state="normal")
        for i in range(len(r) - 2, -1, -2):     # last-to-first: indices stay valid
            self.chat.delete(r[i], r[i + 1])
        self.chat.configure(state="disabled")
        return True

    def _animate_note(self):
        self._note_job = None
        r = self.chat.tag_ranges("gen_note")
        if not r or not self.generating:
            return
        pos = self.chat.index(r[0])
        self._note_dots = (self._note_dots + 1) % 4
        self._delete_note_ranges()
        self.chat.configure(state="normal")
        self.chat.insert(pos, self._note_base + "." * self._note_dots,
                         ("system", "gen_note"))
        self.chat.configure(state="disabled")
        self._note_job = self.after(400, self._animate_note)

    def _note_clear(self):
        if self._note_job:
            self.after_cancel(self._note_job)
            self._note_job = None
        self._delete_note_ranges()

    def _start_generation(self, make_gen, fold_after=False, note="generating"):
        self.generating = True
        self.send_btn.configure(state="disabled")
        self._note_show(note)
        engine = self.engine  # snapshot: a mid-turn story switch can't misdirect
        store = self.store     # the fold to a different story's memory

        def worker():
            try:
                for piece in make_gen(engine):
                    self.msg_queue.put(("chunk", piece))
                if fold_after and engine is self.engine and store is self.store:
                    for event in engine.maybe_fold():
                        self.msg_queue.put(("system", f"\n· {event}\n"))
            except Exception as e:  # noqa: BLE001
                self.msg_queue.put(("error", str(e)))
            self.msg_queue.put(("done", None))

        threading.Thread(target=worker, daemon=True).start()

    def _drain_queue(self):
        try:
            while True:
                kind, val = self.msg_queue.get_nowait()
                if kind == "chunk":
                    self._note_clear()          # prose is landing — drop the spinner
                    self._append(val, "narration")
                elif kind == "system":
                    self._append(val, "system")
                elif kind == "gen_done":
                    slug, title = val
                    self._append(f"· scenario '{title}' ready — Save ▸ New save to "
                                 f"start a playthrough from it.\n", "system")
                elif kind == "error":
                    # Report inline (not a modal) so a burst of errors can't stack
                    # dialogs and stall the drain pump. Generic label: the failure
                    # may be local (a bad memory file), not the model.
                    self._note_clear()
                    self._append(f"\n[error: {val}]\n", "system")
                elif kind == "done":
                    self.generating = False
                    self._note_clear()
                    self.send_btn.configure(state="normal")
                    self._refresh_sheet_panel()   # show this turn's RPG deltas
                    if (self.store is not None and not self.store.has_turns()
                            and self._opening_attempted):
                        self._append("\n· the opening didn't generate — press "
                                     "Retry to try again.\n", "system")
                    # Refresh the editor to post-fold disk state (the fold may have
                    # rewritten state.json/characters.md/scenes.md), but never
                    # clobber unsaved edits the user typed while it ran.
                    if not self.mem_edit.edit_modified():
                        self._load_mem_file()
        except queue.Empty:
            pass
        self.after(50, self._drain_queue)

    # ---------- story management ----------
    def _load_stories_list(self):
        self._stories = self.lib.list_stories()
        self._story_labels = {f"{s['title']}  ({s['slug']})": s["slug"]
                              for s in self._stories}
        self.story_combo["values"] = list(self._story_labels)

    def _ensure_story(self):
        if self._stories:
            self._open_story(self._stories[0]["slug"])
        else:
            self.new_story_dialog()

    def _on_story_select(self, _evt):
        if self.generating:
            # don't swap stories mid-generation; restore the combobox selection
            self._set_story_combo(self.slug)
            messagebox.showinfo("Busy", "Finish the current turn first.")
            return
        label = self.story_var.get()
        if label in self._story_labels:
            self._open_story(self._story_labels[label])

    def _set_story_combo(self, slug):
        for label, s in self._story_labels.items():
            if s == slug:
                self.story_var.set(label)
                return

    def _open_story(self, slug):
        self.slug = slug
        self.store = self.lib.open(slug)  # session-open snapshot (I-148/ESC-4)
        self.engine = Engine(self.cfg, self.store)
        self._set_story_combo(slug)
        self._refresh_rpg_btn()
        self._refresh_sheet_panel()   # retarget an open sheet to the new save
        self._ed_load_files()         # retarget the piece editor too
        self._marks_slug = None       # old retry/undo marks belong to the old page
        self.chat.configure(state="normal")
        self.chat.delete("1.0", "end")
        self.chat.configure(state="disabled")
        turns = self.store.turns()
        self._opening_attempted = not turns
        if not turns:
            self._start_generation(lambda eng: eng.opening(on_stage=self._stage_cb),
                                   note="setting the scene")
        else:
            for t in turns:
                if t["role"] == "player":
                    self._append(f"\n> {t['text']}\n\n", "player")
                else:
                    self._append(t["text"], "narration")
        self._load_mem_file()

    _CUSTOM = "<New custom world...>"

    def new_story_dialog(self):
        if self.generating:
            messagebox.showinfo("Busy", "Finish the current turn first.")
            return
        dlg = tk.Toplevel(self)
        dlg.title("New save")
        dlg.configure(bg=BG)
        dlg.transient(self)
        dlg.grab_set()
        self.after_idle(lambda: self._place_dialog(dlg))

        scens = self.lib.scenarios.list()
        scen_labels = {f"{s['title']}  ({s['slug']})": s["slug"] for s in scens}
        values = list(scen_labels) + [self._CUSTOM]

        tk.Label(dlg, text="Scenario:", bg=BG).grid(row=0, column=0, sticky="e",
                                                    padx=6, pady=6)
        scen_var = tk.StringVar(value=values[0])
        scen_cb = ttk.Combobox(dlg, textvariable=scen_var, state="readonly",
                               values=values, width=44)
        scen_cb.grid(row=0, column=1, padx=6, pady=6)

        tk.Label(dlg, text="Save name:", bg=BG).grid(row=1, column=0, sticky="e",
                                                    padx=6, pady=6)
        name_e = tk.Entry(dlg, width=46, relief="sunken", bd=2)
        name_e.grid(row=1, column=1, padx=6, pady=6, sticky="w")

        mode_var = tk.StringVar(value="simple")
        mrow = tk.Frame(dlg, bg=BG)
        mrow.grid(row=2, column=1, sticky="w", padx=6)
        tk.Label(mrow, text="Mode:", bg=BG).pack(side="left")
        tk.Radiobutton(mrow, text="Simple story (fast, pure narrative)",
                       variable=mode_var, value="simple", bg=BG,
                       activebackground=BG).pack(side="left", padx=4)
        tk.Radiobutton(mrow, text="RPG campaign (stats, dice, quests)",
                       variable=mode_var, value="rpg", bg=BG,
                       activebackground=BG).pack(side="left", padx=4)

        # custom-world fields (shown only when <New custom world...> is chosen)
        custom = tk.LabelFrame(dlg, text="New custom world", bg=BG, padx=6, pady=4)
        tk.Label(custom, text="World title:", bg=BG).grid(row=0, column=0, sticky="e")
        cust_title = tk.Entry(custom, width=42, relief="sunken", bd=2)
        cust_title.grid(row=0, column=1, padx=4, pady=2)
        tk.Label(custom, text="Premise:", bg=BG).grid(row=1, column=0, sticky="ne")
        cust_prem = tk.Text(custom, width=42, height=5, relief="sunken", bd=2)
        cust_prem.grid(row=1, column=1, padx=4, pady=2)
        cust_prem.insert("1.0", DEFAULT_PREMISE)

        def on_scen(_e=None):
            if scen_var.get() == self._CUSTOM:
                custom.grid(row=3, column=0, columnspan=2, padx=6, pady=6, sticky="we")
            else:
                custom.grid_forget()
        scen_cb.bind("<<ComboboxSelected>>", on_scen)

        def create():
            if scen_var.get() == self._CUSTOM:
                wtitle = cust_title.get().strip() or "Untitled World"
                premise = cust_prem.get("1.0", "end").strip() or DEFAULT_PREMISE
                scen_slug = self.lib.scenarios.create(wtitle, premise)
                default_name = wtitle
            else:
                scen_slug = scen_labels[scen_var.get()]
                default_name = next(s["title"] for s in scens if s["slug"] == scen_slug)
            save_title = name_e.get().strip() or default_name
            slug = self.lib.saves.create(save_title, scen_slug,
                                         mode=mode_var.get(),
                                         rpg_cfg=self.cfg.rpg)
            self._load_stories_list()
            dlg.destroy()
            self._open_story(slug)

        btns = tk.Frame(dlg, bg=BG)
        btns.grid(row=4, column=0, columnspan=2, pady=8)
        self._button(btns, "Create", create).pack(side="left", padx=4)
        self._button(btns, "Cancel", dlg.destroy).pack(side="left", padx=4)
        name_e.focus_set()

    def _new_scenario_dialog(self):
        dlg = tk.Toplevel(self)
        dlg.title("New scenario (reusable world)")
        dlg.configure(bg=BG)
        dlg.transient(self)
        dlg.grab_set()
        self.after_idle(lambda: self._place_dialog(dlg))
        tk.Label(dlg, text="Title:", bg=BG).grid(row=0, column=0, sticky="e",
                                                 padx=6, pady=6)
        title_e = tk.Entry(dlg, width=48, relief="sunken", bd=2)
        title_e.grid(row=0, column=1, padx=6, pady=6)
        tk.Label(dlg, text="Premise:", bg=BG).grid(row=1, column=0, sticky="ne",
                                                   padx=6, pady=6)
        prem = tk.Text(dlg, width=48, height=6, relief="sunken", bd=2)
        prem.grid(row=1, column=1, padx=6, pady=6)
        prem.insert("1.0", DEFAULT_PREMISE)

        def create():
            title = title_e.get().strip() or "Untitled World"
            self.lib.scenarios.create(title, prem.get("1.0", "end").strip()
                                      or DEFAULT_PREMISE)
            dlg.destroy()
            messagebox.showinfo("Scenario created",
                                f"'{title}' is ready. Use Save ▸ New save to start a "
                                f"playthrough from it.")
        btns = tk.Frame(dlg, bg=BG)
        btns.grid(row=2, column=0, columnspan=2, pady=8)
        self._button(btns, "Create", create).pack(side="left", padx=4)
        self._button(btns, "Cancel", dlg.destroy).pack(side="left", padx=4)
        title_e.focus_set()

    def _generate_scenario_dialog(self):
        if self.generating:
            messagebox.showinfo("Busy", "Finish the current turn first.")
            return
        dlg = tk.Toplevel(self)
        dlg.title("Generate scenario (AI)")
        dlg.configure(bg=BG)
        dlg.transient(self)
        dlg.grab_set()
        self.after_idle(lambda: self._place_dialog(dlg))
        tk.Label(dlg, text="Type:", bg=BG).grid(row=0, column=0, sticky="e",
                                                padx=6, pady=4)
        type_e = tk.Entry(dlg, width=46, relief="sunken", bd=2)
        type_e.grid(row=0, column=1, padx=6, pady=4)
        tk.Label(dlg, text="Tone:", bg=BG).grid(row=1, column=0, sticky="e",
                                                padx=6, pady=4)
        tone_e = tk.Entry(dlg, width=46, relief="sunken", bd=2)
        tone_e.grid(row=1, column=1, padx=6, pady=4)
        tk.Label(dlg, text="Premise:", bg=BG).grid(row=2, column=0, sticky="ne",
                                                   padx=6, pady=4)
        sum_t = tk.Text(dlg, width=46, height=4, relief="sunken", bd=2)
        sum_t.grid(row=2, column=1, padx=6, pady=4)
        improve_var = tk.BooleanVar(value=False)
        tk.Checkbutton(dlg, text="Improve my prompt first (AI detailer pass)",
                       variable=improve_var, bg=BG, activebackground=BG
                       ).grid(row=6, column=0, columnspan=2)
        tk.Label(dlg, text="Leave any field blank to let the AI decide (it holds the "
                           "tone).", bg=BG, fg="#606060", wraplength=380,
                 justify="left").grid(row=3, column=0, columnspan=2, padx=6)
        counts = tk.Frame(dlg, bg=BG)
        counts.grid(row=4, column=0, columnspan=2, pady=6)
        spins = {}
        for i, (lbl, key) in enumerate([("NPCs", "n_npcs"), ("Locations", "n_locations"),
                                        ("Items", "n_items")]):
            tk.Label(counts, text=lbl + ":", bg=BG).grid(row=0, column=i * 2, padx=(8, 2))
            sp = tk.Spinbox(counts, from_=0, to=20, width=4)
            sp.delete(0, "end")
            sp.insert(0, "5")
            sp.grid(row=0, column=i * 2 + 1)
            spins[key] = sp
        detail_var = tk.StringVar(value="rich")
        drow = tk.Frame(dlg, bg=BG)
        drow.grid(row=5, column=0, columnspan=2)
        tk.Label(drow, text="Detail:", bg=BG).pack(side="left", padx=(8, 4))
        tk.Radiobutton(drow, text="rich (one call per entity — slow but deep)",
                       variable=detail_var, value="rich", bg=BG,
                       activebackground=BG).pack(side="left")
        tk.Radiobutton(drow, text="fast (batched)", variable=detail_var,
                       value="fast", bg=BG, activebackground=BG).pack(side="left",
                                                                      padx=6)

        def go():
            def _n(sp):
                try:
                    return max(0, min(20, int(sp.get())))
                except ValueError:
                    return 5
            spec = ScenarioSpec(
                type=type_e.get().strip(), tone=tone_e.get().strip(),
                premise=sum_t.get("1.0", "end").strip(),
                n_npcs=_n(spins["n_npcs"]), n_locations=_n(spins["n_locations"]),
                n_items=_n(spins["n_items"]), detail=detail_var.get(),
                improve=bool(improve_var.get()))
            dlg.destroy()
            self._run_generation(spec)

        btns = tk.Frame(dlg, bg=BG)
        btns.grid(row=7, column=0, columnspan=2, pady=8)
        self._button(btns, "Generate", go).pack(side="left", padx=4)
        self._button(btns, "Cancel", dlg.destroy).pack(side="left", padx=4)
        type_e.focus_set()

    def _run_generation(self, spec):
        """Generate a scenario on a worker thread; progress + result flow back through
        the same msg_queue the turn pump uses (keeps the UI responsive)."""
        self.generating = True
        self.send_btn.configure(state="disabled")
        self._append("\n· generating scenario (several model calls, please wait)…\n",
                     "system")
        self._note_show("generating scenario")
        llm = LLM(self.cfg.profile, self.cfg.generation)

        def worker():
            try:
                slug = generate_scenario(
                    self.lib, llm, spec,
                    on_stage=lambda s: self.msg_queue.put(("system", f"  · {s}\n")))
                title = next((sc["title"] for sc in self.lib.scenarios.list()
                              if sc["slug"] == slug), slug)
                for w in generate_scenario.last_warnings:
                    self.msg_queue.put(("system", f"  ! {w}\n"))
                self.msg_queue.put(("gen_done", (slug, title)))
            except Exception as e:  # noqa: BLE001
                self.msg_queue.put(("error", str(e)))
            self.msg_queue.put(("done", None))

        threading.Thread(target=worker, daemon=True).start()

    def _delete_scenario_dialog(self):
        scens = self.lib.scenarios.list()
        if not scens:
            messagebox.showinfo("Scenarios", "There are no scenarios to delete.")
            return
        dlg = tk.Toplevel(self)
        dlg.title("Delete scenario")
        dlg.configure(bg=BG)
        dlg.transient(self)
        dlg.grab_set()
        self.after_idle(lambda: self._place_dialog(dlg))
        tk.Label(dlg, text="Delete which world?", bg=BG).grid(
            row=0, column=0, sticky="e", padx=6, pady=6)
        labels = {f"{s['title']}  ({s['slug']})": s["slug"] for s in scens}
        var = tk.StringVar(value=next(iter(labels)))
        ttk.Combobox(dlg, textvariable=var, state="readonly",
                     values=list(labels), width=40).grid(row=0, column=1, padx=6, pady=6)
        tk.Label(dlg, wraplength=360, justify="left", bg=BG, fg="#606060",
                 text="Existing saves keep their own copied world. Any save that "
                      "inherited a rule override from this scenario will revert to the "
                      "global rules.").grid(row=1, column=0, columnspan=2, padx=6)

        def do_delete():
            slug = labels[var.get()]
            if messagebox.askyesno("Delete scenario",
                                   f"Delete scenario '{var.get()}'?"):
                self.lib.scenarios.delete(slug)
                dlg.destroy()
        btns = tk.Frame(dlg, bg=BG)
        btns.grid(row=2, column=0, columnspan=2, pady=8)
        self._button(btns, "Delete", do_delete).pack(side="left", padx=4)
        self._button(btns, "Cancel", dlg.destroy).pack(side="left", padx=4)

    # ---------- save management ----------
    def _guard(self) -> bool:
        if self.generating:
            messagebox.showinfo("Busy", "Finish the current turn first.")
            return False
        if self.store is None or self.slug is None:
            return False
        return True

    def _duplicate_save(self):
        if not self._guard():
            return
        new_slug = self.lib.saves.duplicate(self.slug)
        self._load_stories_list()
        self._open_story(new_slug)
        messagebox.showinfo("Duplicated",
                            f"Branched into '{self.store.title}'. The original is "
                            f"untouched.")

    def _branch_save(self):
        """Wave 4: fork the story at a chosen turn — a new save whose transcript,
        state, and memory are as of that moment; the original stays untouched."""
        if not self._guard():
            return
        total = len(self.store.turns())
        if total < 1:
            messagebox.showinfo("Branch", "Nothing to branch from yet.")
            return
        n = simpledialog.askinteger(
            "Branch from turn", f"Fork at which turn? (1..{total})",
            initialvalue=total, minvalue=1, maxvalue=total, parent=self)
        if not n:
            return
        new_slug, warns = self.lib.saves.branch(self.slug, n, self.cfg.rpg)
        self._load_stories_list()
        self._open_story(new_slug)
        note = f"Forked at turn {n} into '{self.store.title}'."
        if warns:
            note += "\n\nNote: " + "; ".join(warns) + "."
        messagebox.showinfo("Branched", note)

    def _rename_save(self):
        if not self._guard():
            return
        new = simpledialog.askstring("Rename save", "New name:",
                                     initialvalue=self.store.title, parent=self)
        if new and new.strip():
            self.lib.saves.rename(self.slug, new.strip())
            self._load_stories_list()
            self._set_story_combo(self.slug)

    def _delete_save(self):
        if not self._guard():
            return
        if not messagebox.askyesno(
                "Delete save",
                f"Delete '{self.store.title}' and its snapshots? This cannot be "
                f"undone."):
            return
        victim = self.slug
        self.lib.saves.delete(victim)
        self._load_stories_list()
        remaining = self.lib.list_stories()
        if remaining:
            self._open_story(remaining[0]["slug"])
        else:
            self.store = self.engine = self.slug = None
            self.new_story_dialog()

    def _export_save(self):
        if not self._guard():
            return
        path = filedialog.asksaveasfilename(
            title="Export save", defaultextension=".zip",
            initialfile=f"{self.slug}.zip", filetypes=[("Zip archive", "*.zip")])
        if path:
            self.lib.saves.export(self.slug, path)
            messagebox.showinfo("Exported", f"Saved to:\n{path}")

    def _import_save(self):
        if self.generating:
            messagebox.showinfo("Busy", "Finish the current turn first.")
            return
        path = filedialog.askopenfilename(
            title="Import save", filetypes=[("Zip archive", "*.zip")])
        if path:
            new_slug = self.lib.saves.import_(path)
            self._load_stories_list()
            self._open_story(new_slug)

    # ---------- SETTINGS TAB ----------
    def _build_settings(self):
        # Six option groups no longer fit a small window — wrap them in a scrollable
        # body so nothing clips or crushes at any size.
        canvas = tk.Canvas(self.tab_settings, bg=BG, highlightthickness=0)
        vsb = tk.Scrollbar(self.tab_settings, orient="vertical",
                           command=canvas.yview)
        canvas.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)
        body = tk.Frame(canvas, bg=BG)
        body_win = canvas.create_window((0, 0), window=body, anchor="nw")
        body.bind("<Configure>",
                  lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>",
                    lambda e: canvas.itemconfigure(body_win, width=e.width))

        def _wheel(e):
            canvas.yview_scroll(int(-e.delta / 120), "units")
        body.bind("<Enter>", lambda e: canvas.bind_all("<MouseWheel>", _wheel))
        body.bind("<Leave>", lambda e: canvas.unbind_all("<MouseWheel>"))

        raw = self.cfg.raw
        prof = self._group(body, "Model profile")
        prof.pack(fill="x", padx=8, pady=6)
        tk.Label(prof, text="Active profile:", bg=BG).grid(row=0, column=0, sticky="e")
        self.profile_var = tk.StringVar(value=raw["active_profile"])
        pc = ttk.Combobox(prof, textvariable=self.profile_var, state="readonly",
                          values=list(raw["profiles"]), width=18)
        pc.grid(row=0, column=1, sticky="w", padx=4, pady=2)
        pc.bind("<<ComboboxSelected>>", self._on_profile_change)

        self.p_base = self._labeled_entry(prof, "Base URL:", 1, width=46)
        self.p_model = self._labeled_entry(prof, "Model:", 2, width=46)
        self.p_ctx = self._labeled_entry(prof, "Context tokens:", 3, width=12)
        ctx_hint = tk.Frame(prof, bg=BG)
        ctx_hint.grid(row=3, column=2, sticky="w", padx=4)
        tk.Label(ctx_hint,
                 text=f"recommended ≥ {models_mod.RECOMMENDED_MIN_CONTEXT:,}; "
                      "131k+ fully supported",
                 bg=BG, fg="#606060").pack(side="left")
        self._button(ctx_hint, "Model sizes…", self._show_context_hints,
                     width=12).pack(side="left", padx=6)
        self.p_key = self._labeled_entry(prof, "API key:", 4, width=46, show="*")
        self.p_keyenv_lbl = tk.Label(prof, text="", bg=BG, fg="#606060")
        self.p_keyenv_lbl.grid(row=5, column=1, sticky="w")

        gen = self._group(body, "Generation")
        gen.pack(fill="x", padx=8, pady=6)
        g = self.cfg.generation
        self.g_temp = self._labeled_entry(gen, "Temperature:", 0, width=10,
                                          value=g.get("temperature", 0.9))
        self.g_top = self._labeled_entry(gen, "Top-p:", 1, width=10,
                                         value=g.get("top_p", 0.95))
        self.g_max = self._labeled_entry(gen, "Max tokens:", 2, width=10,
                                         value=g.get("max_tokens", 700))
        self.think_var = tk.BooleanVar(value=bool(g.get("think", False)))
        tk.Checkbutton(gen, text="Thinking mode (slower, for reasoning)",
                       variable=self.think_var, bg=BG,
                       activebackground=BG).grid(row=3, column=1, sticky="w", pady=2)
        self.tool_var = tk.BooleanVar(value=bool(g.get("use_memory_tool", False)))
        tk.Checkbutton(gen,
                       text="Memory lookup tool  (big-context / hosted models only)",
                       variable=self.tool_var, bg=BG,
                       activebackground=BG).grid(row=4, column=1, sticky="w", pady=2)
        self.length_var = tk.StringVar(
            value=str(g.get("response_length", "medium")))
        lrow = tk.Frame(gen, bg=BG)
        lrow.grid(row=7, column=1, sticky="w", pady=2)
        tk.Label(lrow, text="Response length:", bg=BG).pack(side="left")
        for val in ("short", "medium", "long"):
            tk.Radiobutton(lrow, text=val, variable=self.length_var, value=val,
                           bg=BG, activebackground=BG).pack(side="left", padx=3)
        self.trinity_var = tk.BooleanVar(value=bool(g.get("trinity_brain", False)))
        tk.Checkbutton(gen,
                       text="Quad Brain  (Director→Validator→Writer; ~2x slower)",
                       variable=self.trinity_var, bg=BG,
                       activebackground=BG).grid(row=5, column=1, sticky="w", pady=2)
        tcfg = self.cfg.raw.get("trinity") or {}
        lk = tcfg.get("lorekeeper") or {}
        self.lore_pass_var = tk.BooleanVar(
            value=bool(lk.get("llm_pass", False) if isinstance(lk, dict) else False))
        tk.Checkbutton(gen,
                       text="Lore-keeper LLM pass  (extra per-turn continuity call)",
                       variable=self.lore_pass_var, bg=BG,
                       activebackground=BG).grid(row=6, column=1, sticky="w", pady=2)

        tri = self._group(body,
                          "Quad Brain — per-stage model / API (blank = use active profile)")
        tri.pack(fill="x", padx=8, pady=6)
        prof_choices = ["(active)"] + list(raw["profiles"])
        self.tri_rows = {}
        for i, (stage, label) in enumerate([("director", "Director (logic):"),
                                            ("lorekeeper", "Lore-keeper:"),
                                            ("writer", "Writer (prose):")]):
            tk.Label(tri, text=label, bg=BG).grid(row=i, column=0, sticky="e",
                                                  padx=4, pady=2)
            scfg = tcfg.get(stage) or {}
            pvar = tk.StringVar(value=scfg.get("profile") or "(active)")
            ttk.Combobox(tri, textvariable=pvar, state="readonly",
                         values=prof_choices, width=14).grid(row=i, column=1,
                                                             sticky="w", padx=4, pady=2)
            tk.Label(tri, text="model:", bg=BG).grid(row=i, column=2, sticky="e", padx=4)
            mentry = tk.Entry(tri, width=30, relief="sunken", bd=2)
            mentry.grid(row=i, column=3, sticky="w", padx=4, pady=2)
            if scfg.get("model"):
                mentry.insert(0, str(scfg["model"]))
            self.tri_rows[stage] = (pvar, mentry)

        mem = self._group(body, "Memory")
        mem.pack(fill="x", padx=8, pady=6)
        m = self.cfg.memory
        self.m_short = self._labeled_entry(mem, "Short-term turns:", 0, width=10,
                                           value=m.get("short_term_turns", 12))
        self.m_mfa = self._labeled_entry(mem, "Medium fold after:", 1, width=10,
                                         value=m.get("medium_fold_after", 12))
        self.m_mfs = self._labeled_entry(mem, "Medium fold size:", 2, width=10,
                                         value=m.get("medium_fold_size", 6))
        self.m_lfa = self._labeled_entry(mem, "Long fold after:", 3, width=10,
                                         value=m.get("long_fold_after", 8))
        self.m_lfs = self._labeled_entry(mem, "Long fold size:", 4, width=10,
                                         value=m.get("long_fold_size", 4))

        ret = self._group(body, "Retrieval (semantic recall — Phase 5)")
        ret.pack(fill="x", padx=8, pady=6)
        r = self.cfg.retrieval
        self.ret_enabled = tk.BooleanVar(value=bool(r.get("enabled", False)))
        tk.Checkbutton(ret, text="Vector semantic recall  (needs an embeddings model, "
                                 "e.g. `ollama pull nomic-embed-text`)",
                       variable=self.ret_enabled, bg=BG,
                       activebackground=BG).grid(row=0, column=1, sticky="w", pady=2)
        self.ret_model = self._labeled_entry(ret, "Embed model:", 1, width=28,
                                             value=r.get("embed_model", "nomic-embed-text"))
        self.ret_topk = self._labeled_entry(ret, "Top-K recalled:", 2, width=10,
                                            value=r.get("top_k", 4))

        bar = tk.Frame(body, bg=BG)
        bar.pack(fill="x", padx=8, pady=8)
        self._button(bar, "Save & apply", self._save_settings, width=14).pack(side="left")
        self.set_status = tk.Label(bar, text="", bg=BG, fg=NAVY)
        self.set_status.pack(side="left", padx=8)

        self._load_profile_fields(raw["active_profile"])

    def _labeled_entry(self, parent, label, row, width=20, value="", show=None):
        tk.Label(parent, text=label, bg=BG).grid(row=row, column=0, sticky="e",
                                                 padx=4, pady=2)
        e = tk.Entry(parent, width=width, relief="sunken", bd=2, show=show)
        e.grid(row=row, column=1, sticky="w", padx=4, pady=2)
        if value != "":
            e.insert(0, str(value))
        return e

    def _on_profile_change(self, _evt):
        self._load_profile_fields(self.profile_var.get())

    def _load_profile_fields(self, name):
        p = self.cfg.raw["profiles"][name]
        for e, v in ((self.p_base, p.get("base_url", "")),
                     (self.p_model, p.get("model", "")),
                     (self.p_ctx, p.get("context_tokens", ""))):
            e.delete(0, "end")
            e.insert(0, str(v))
        key_env = p.get("api_key_env", "")
        env = read_env()
        self.p_key.delete(0, "end")
        self.p_key.insert(0, env.get(key_env, ""))
        self.p_keyenv_lbl.configure(text=f"(stored in .env as {key_env})")

    def _save_settings(self):
        if self.generating:
            messagebox.showinfo("Busy", "Finish the current turn before applying "
                                        "settings.")
            return
        raw = self.cfg.raw
        name = self.profile_var.get()
        raw["active_profile"] = name
        prof = raw["profiles"][name]
        prof["base_url"] = self.p_base.get().strip()
        prof["model"] = self.p_model.get().strip()
        prof["context_tokens"] = int(_num(self.p_ctx.get(),
                                          prof.get("context_tokens", 8192)))
        raw.setdefault("generation", {})
        raw["generation"].update({
            "temperature": _num(self.g_temp.get(), 0.9),
            "top_p": _num(self.g_top.get(), 0.95),
            "max_tokens": int(_num(self.g_max.get(), 700)),
            "think": bool(self.think_var.get()),
            "use_memory_tool": bool(self.tool_var.get()),
            "trinity_brain": bool(self.trinity_var.get()),
            "response_length": self.length_var.get(),
        })
        raw.setdefault("memory", {})
        raw["memory"].update({
            "short_term_turns": int(_num(self.m_short.get(), 12)),
            "medium_fold_after": int(_num(self.m_mfa.get(), 12)),
            "medium_fold_size": int(_num(self.m_mfs.get(), 6)),
            "long_fold_after": int(_num(self.m_lfa.get(), 8)),
            "long_fold_size": int(_num(self.m_lfs.get(), 4)),
        })
        raw.setdefault("retrieval", {})
        raw["retrieval"].update({
            "enabled": bool(self.ret_enabled.get()),
            "embed_model": self.ret_model.get().strip() or "nomic-embed-text",
            "top_k": int(_num(self.ret_topk.get(), 4)),
        })
        # Per-stage Quad models/APIs: keep only stages the user actually pinned
        # (plus the lore-keeper's opt-in LLM pass flag).
        trinity = {}
        for stage, (pvar, mentry) in self.tri_rows.items():
            scfg = {}
            pname = pvar.get()
            if pname and pname != "(active)":
                scfg["profile"] = pname
            model = mentry.get().strip()
            if model:
                scfg["model"] = model
            if scfg:
                trinity[stage] = scfg
        if bool(self.lore_pass_var.get()):
            trinity.setdefault("lorekeeper", {})["llm_pass"] = True
        if trinity:
            raw["trinity"] = trinity
        else:
            raw.pop("trinity", None)
        save_yaml(raw)
        key_env = prof.get("api_key_env", "")
        if key_env:
            write_env({key_env: self.p_key.get().strip()})
        self.cfg = load_config()
        if self.store is not None:
            self.engine = Engine(self.cfg, self.store)
        self.set_status.configure(text="Saved. Applied to current session.")
        self.after(2500, lambda: self.set_status.configure(text=""))

    # ---------- MEMORY TAB (file editor) ----------
    # ---------- Editor tab (Wave 4: FictionLab-style piece editor) ----------
    # Structured form over the SAME md entries the Memory tab edits raw — every
    # save writes through Entry/upsert, so hand-editing stays fully equivalent.
    _ED_ATTRS = ["status", "weight", "pinned", "hidden", "triggers", "links",
                 "stats", "skills", "rarity", "objectives", "companion",
                 "type", "once"]

    def _build_editor(self):
        left = tk.Frame(self.tab_editor, bg=BG)
        left.pack(side="left", fill="y", padx=8, pady=8)
        tk.Label(left, text="Lore file:", bg=BG).pack(anchor="w")
        self.ed_file_var = tk.StringVar()
        self.ed_file_box = ttk.Combobox(left, textvariable=self.ed_file_var,
                                        state="readonly", width=24)
        self.ed_file_box.pack(anchor="w", pady=(0, 4))
        self.ed_file_box.bind("<<ComboboxSelected>>",
                              lambda e: self._ed_file_changed())
        self.ed_list = tk.Listbox(left, width=28, height=22, relief="sunken",
                                  bd=2, exportselection=False)
        self.ed_list.pack(fill="y", expand=True)
        self.ed_list.bind("<<ListboxSelect>>", lambda e: self._ed_load_entry())
        lbtn = tk.Frame(left, bg=BG)
        lbtn.pack(fill="x", pady=4)
        self._button(lbtn, "New piece", self._ed_new, width=10).pack(side="left")
        self._button(lbtn, "Delete", self._ed_delete, width=8).pack(
            side="left", padx=4)
        self._button(left, "Add lore type…", self._ed_add_type,
                     width=20).pack(anchor="w")

        right = tk.Frame(self.tab_editor, bg=BG)
        right.pack(side="left", fill="both", expand=True, padx=8, pady=8)
        self.ed_fields: dict[str, tk.Widget] = {}

        def entry_row(row, label, key, width=52):
            tk.Label(right, text=label, bg=BG).grid(row=row, column=0,
                                                    sticky="e", padx=4, pady=1)
            e = tk.Entry(right, width=width, relief="sunken", bd=2)
            e.grid(row=row, column=1, columnspan=3, sticky="w", padx=4, pady=1)
            self.ed_fields[key] = e
            return e

        entry_row(0, "Title:", "title")
        entry_row(1, "Slug:", "slug", width=30)
        entry_row(2, "Aliases (a, b):", "aliases")
        tk.Label(right, text="Importance:", bg=BG).grid(row=3, column=0,
                                                        sticky="e", padx=4)
        imp = tk.Spinbox(right, from_=1, to=5, width=4, relief="sunken", bd=2)
        imp.grid(row=3, column=1, sticky="w", padx=4)
        self.ed_fields["importance"] = imp
        tk.Label(right, text="Weight:", bg=BG).grid(row=3, column=2, sticky="e",
                                                    padx=4)
        wgt = ttk.Combobox(right, state="readonly", width=14,
                           values=["", "minor", "supplementary", "standard",
                                   "important", "critical"])
        wgt.grid(row=3, column=3, sticky="w", padx=4)
        self.ed_fields["weight"] = wgt
        flags = tk.Frame(right, bg=BG)
        flags.grid(row=4, column=1, columnspan=3, sticky="w", padx=4)
        for key, label in (("pinned", "pinned (always in context)"),
                           ("hidden", "hidden (secret — AI foreshadows only)"),
                           ("companion", "companion"),
                           ("once", "once (event rules)")):
            var = tk.BooleanVar(value=False)
            tk.Checkbutton(flags, text=label, variable=var, bg=BG,
                           activebackground=BG).pack(side="left", padx=3)
            self.ed_fields[key] = var
        entry_row(5, "Triggers (words):", "triggers")
        entry_row(6, "Links (slugs):", "links")
        entry_row(7, "Status:", "status")
        entry_row(8, "Stats (str 3, agi 2):", "stats")
        entry_row(9, "Skills (name (stat)):", "skills")
        tk.Label(right, text="Rarity:", bg=BG).grid(row=10, column=0,
                                                    sticky="e", padx=4)
        rar = ttk.Combobox(right, state="readonly", width=14,
                           values=["", "common", "uncommon", "rare", "epic",
                                   "legendary"])
        rar.grid(row=10, column=1, sticky="w", padx=4)
        self.ed_fields["rarity"] = rar
        entry_row(11, "Objectives (a; b):", "objectives")
        entry_row(12, "Type:", "type", width=20)
        tk.Label(right, text="Body:", bg=BG).grid(row=13, column=0, sticky="ne",
                                                  padx=4, pady=(4, 0))
        self.ed_body = tk.Text(right, width=64, height=12, font=("Consolas", 10),
                               relief="sunken", bd=2, wrap="word",
                               undo=True)
        self.ed_body.grid(row=13, column=1, columnspan=3, sticky="nsew",
                          padx=4, pady=(4, 0))
        right.grid_rowconfigure(13, weight=1)
        right.grid_columnconfigure(3, weight=1)
        brow = tk.Frame(right, bg=BG)
        brow.grid(row=14, column=1, columnspan=3, sticky="w", pady=6)
        self._button(brow, "Save piece", self._ed_save, width=12).pack(side="left")
        self.ed_status = tk.Label(brow, text="", bg=BG, fg=NAVY)
        self.ed_status.pack(side="left", padx=8)
        self._ed_current = None      # (rel, slug) being edited
        self._ed_load_files()

    def _ed_registries(self) -> list[str]:
        if self.store is None:
            return []
        return (["player.md"] + self.store.gated_registries()
                + ["threads.md", "events.md"])

    def _ed_load_files(self):
        if not hasattr(self, "ed_file_box"):
            return
        # A save switch invalidates whatever the form was editing — a stale
        # (file, slug) here would make Save/Delete hit the NEW save's files.
        self._ed_current = None
        files = self._ed_registries()
        self.ed_file_box.configure(values=files)
        if files and self.ed_file_var.get() not in files:
            self.ed_file_var.set(files[1] if len(files) > 1 else files[0])
        self._ed_load_list()

    def _ed_file_changed(self):
        # Switching lore files drops the edit context: saving the old form into
        # the newly selected file (or deleting its same-named entry) corrupted
        # registries before this reset existed.
        self._ed_current = None
        if hasattr(self, "ed_status"):
            self.ed_status.configure(text="")
        self._ed_load_list()

    def _ed_load_list(self):
        self.ed_list.delete(0, "end")
        if self.store is None or not self.ed_file_var.get():
            return
        for e in self.store.entries(self.ed_file_var.get()):
            marks = ("*" if e.pinned() else "") \
                + (" [hidden]" if e.hidden() else "")
            self.ed_list.insert("end", f"{e.title}{marks}")

    def _ed_selected_entry(self):
        sel = self.ed_list.curselection()
        if not sel or self.store is None:
            return None
        entries = self.store.entries(self.ed_file_var.get())
        return entries[sel[0]] if sel[0] < len(entries) else None

    def _ed_load_entry(self):
        e = self._ed_selected_entry()
        if e is None:
            return
        self._ed_current = (self.ed_file_var.get(), e.slug)
        f = self.ed_fields
        for key, val in (("title", e.title), ("slug", e.slug),
                         ("aliases", ", ".join(e.aliases))):
            f[key].delete(0, "end")
            f[key].insert(0, val)
        f["importance"].delete(0, "end")
        f["importance"].insert(0, str(e.importance))
        for key in self._ED_ATTRS:
            w = f.get(key)
            val = e.attrs.get(key, "")
            if isinstance(w, tk.BooleanVar):
                w.set(str(val).strip().lower() in ("true", "yes", "1", "on"))
            elif w is not None:
                if isinstance(w, ttk.Combobox):
                    w.set(val)
                else:
                    w.delete(0, "end")
                    w.insert(0, val)
        self.ed_body.delete("1.0", "end")
        self.ed_body.insert("1.0", e.body)
        self.ed_status.configure(text=f"editing {e.slug}")

    def _ed_new(self):
        self._ed_current = None
        for key in ("title", "slug", "aliases", "triggers", "links", "status",
                    "stats", "skills", "objectives", "type"):
            self.ed_fields[key].delete(0, "end")
        self.ed_fields["importance"].delete(0, "end")
        self.ed_fields["importance"].insert(0, "3")
        for key in ("pinned", "hidden", "companion", "once"):
            self.ed_fields[key].set(False)
        for key in ("weight", "rarity"):
            self.ed_fields[key].set("")
        self.ed_body.delete("1.0", "end")
        self.ed_status.configure(text="new piece — fill the form and Save")

    def _ed_save(self):
        if self.store is None or self.generating:
            return
        from coderain.templates import slugify
        f = self.ed_fields
        title = f["title"].get().strip()
        slug = slugify(f["slug"].get().strip() or title)
        if not title or not slug:
            messagebox.showinfo("Editor", "A piece needs at least a title.")
            return
        rel = self.ed_file_var.get()
        # The loaded piece counts as "being edited" only in ITS OWN file — after
        # a file switch this is a new-piece save, never a cross-file move.
        cur = self._ed_current \
            if (self._ed_current and self._ed_current[0] == rel) else None
        # preserve attrs the form doesn't manage (e.g. turns:, when:, consumed:)
        old = next((e for e in self.store.entries(rel)
                    if cur and e.slug == cur[1]), None)
        attrs = dict(old.attrs) if old else {}
        for key in self._ED_ATTRS:
            w = f.get(key)
            if isinstance(w, tk.BooleanVar):
                val = "true" if w.get() else ""
            elif isinstance(w, ttk.Combobox):
                val = w.get().strip()
            elif w is not None:
                val = w.get().strip()
            else:
                continue
            if val:
                attrs[key] = val
            else:
                attrs.pop(key, None)
        try:
            imp = max(1, min(5, int(f["importance"].get() or 3)))
        except ValueError:
            imp = 3
        entry = Entry(title=title, slug=slug,
                      aliases=[a.strip() for a in f["aliases"].get().split(",")
                               if a.strip()],
                      importance=imp, attrs=attrs,
                      body=self.ed_body.get("1.0", "end").strip())
        self.store.upsert_entry(rel, entry)
        if cur and cur[1] != slug:
            self.store.remove_entry(rel, cur[1])   # slug renamed
        self._ed_current = (rel, slug)
        self._ed_load_list()
        self.ed_status.configure(text=f"saved {slug} → {rel}")

    def _ed_delete(self):
        e = self._ed_selected_entry()
        if e is None or self.store is None:
            return
        rel = self.ed_file_var.get()
        if not messagebox.askyesno("Delete piece",
                                   f"Delete '{e.title}' from {rel}?"):
            return
        self.store.remove_entry(rel, e.slug)
        self._ed_load_list()
        self.ed_status.configure(text=f"deleted {e.slug}")

    def _ed_add_type(self):
        if self.store is None:
            return
        name = simpledialog.askstring(
            "Add lore type", "Name for the new lore file (e.g. Races, Rules):",
            parent=self)
        if not name:
            return
        try:
            rel = self.store.add_custom_file(name)
        except ValueError as e:
            messagebox.showinfo("Add lore type", str(e))
            return
        self._ed_load_files()
        self.ed_file_var.set(rel)
        self._ed_load_list()
        self.ed_status.configure(text=f"added {rel}")

    def _build_memory(self):
        top = tk.Frame(self.tab_memory, bg=BG)
        top.pack(fill="x", padx=6, pady=6)
        tk.Label(top, text="File:", bg=BG).pack(side="left")
        self.mem_file_var = tk.StringVar(value=EDITABLE_FILES[0])
        fc = ttk.Combobox(top, textvariable=self.mem_file_var, state="readonly",
                          values=EDITABLE_FILES, width=22)
        fc.pack(side="left", padx=4)
        fc.bind("<<ComboboxSelected>>", lambda e: self._load_mem_file())
        self._button(top, "Reload", self._load_mem_file, width=8).pack(side="left", padx=2)
        self._button(top, "Save", self._save_mem_file, width=8).pack(side="left", padx=2)
        self.mem_layer = tk.Label(top, text="", bg=BG, fg="#606060")
        self.mem_layer.pack(side="left", padx=8)
        self.mem_override_btn = tk.Button(top, text="", command=self._toggle_override,
                                          relief="raised", bd=2, bg=BG,
                                          activebackground=BG, font=UI_FONT)
        self.mem_reset_btn = tk.Button(top, text="Reset to default",
                                       command=self._reset_rule, relief="raised", bd=2,
                                       bg=BG, activebackground=BG, font=UI_FONT)
        self.mem_status = tk.Label(top, text="", bg=BG, fg=NAVY)
        self.mem_status.pack(side="right", padx=8)

        wrap = tk.Frame(self.tab_memory, bg=TERM_BG, bd=2, relief="sunken")
        wrap.pack(fill="both", expand=True, padx=6, pady=4)
        self.mem_edit = tk.Text(wrap, wrap="word", bg=TERM_BG, fg=TERM_NARR,
                                relief="flat", bd=0, font=EDIT_FONT, padx=10, pady=8,
                                undo=True, insertbackground=TERM_PROMPT, insertwidth=2,
                                selectbackground=TERM_SEL, selectforeground=TERM_PLAYER)
        vsb = tk.Scrollbar(wrap, command=self.mem_edit.yview, bg=TERM_BG,
                           troughcolor="#0c120c", activebackground=TERM_SYS,
                           bd=0, relief="flat", width=12)
        self.mem_edit.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        self.mem_edit.pack(side="left", fill="both", expand=True)
        tk.Label(self.tab_memory,
                 text="Edits change what the engine uses next turn. Rule files "
                      "(writer/memory/rpg) are shared globally unless you make a "
                      "save-specific copy; world + memory files belong to this save.",
                 bg=BG, fg="#606060").pack(anchor="w", padx=8, pady=(0, 6))

    def _load_mem_file(self):
        if self.store is None:
            return
        rel = self.mem_file_var.get()
        self.mem_edit.delete("1.0", "end")
        self.mem_edit.insert("1.0", self.store.read(rel))
        self.mem_edit.edit_reset()
        self.mem_edit.edit_modified(False)  # mark buffer clean after a load
        self.mem_status.configure(text=f"loaded {rel}")
        self._refresh_mem_layer(rel)

    def _refresh_mem_layer(self, rel):
        layer = self.store.layer_of(rel)
        labels = {"global": "shared · global rules", "scenario": "from scenario",
                  "save": "this save"}
        self.mem_layer.configure(text=f"[{labels.get(layer, layer)}]")
        if rel in RULE_FILES:
            self.mem_override_btn.configure(
                text="Revert to shared" if layer == "save" else "Make save-specific")
            self.mem_override_btn.pack(side="left", padx=2)
            self.mem_reset_btn.pack(side="left", padx=2)
        else:
            self.mem_override_btn.pack_forget()
            self.mem_reset_btn.pack_forget()

    def _toggle_override(self):
        if self.store is None or self.generating:
            return
        rel = self.mem_file_var.get()
        if rel not in RULE_FILES:
            return
        # Toggling reloads the editor from disk; don't silently drop unsaved edits.
        if self.mem_edit.edit_modified() and not messagebox.askyesno(
                "Unsaved edits",
                "Switching this file's scope will reload it from disk and discard "
                "your unsaved edits. Continue?"):
            return
        if self.store.layer_of(rel) == "save":
            self.store.remove_override(rel)
        else:
            self.store.make_override(rel)
        self._load_mem_file()

    def _reset_rule(self):
        """Restore the current rule file to its shipped default (at its effective
        layer). The escape hatch for a rule that drifted from the app's default."""
        if self.store is None or self.generating:
            return
        rel = self.mem_file_var.get()
        if rel not in RULE_FILES:
            return
        layer = self.store.layer_of(rel)
        where = {"save": "this save's copy", "scenario": "the scenario's copy"}.get(
            layer, "the shared global rules")
        if not messagebox.askyesno(
                "Reset to default",
                f"Replace {where} of {rel} with the app's shipped default? "
                "Your current text for this file will be lost."):
            return
        self.store.reset_rule(rel)
        self._load_mem_file()
        self.mem_status.configure(text=f"{rel} reset to default")

    def _save_mem_file(self):
        if self.store is None:
            return
        if self.generating:
            messagebox.showinfo("Busy", "Finish the current turn before saving "
                                        "memory (it's being written to).")
            return
        rel = self.mem_file_var.get()
        content = self.mem_edit.get("1.0", "end-1c")
        if rel.endswith(".json"):  # e.g. state.json — don't persist story-breaking JSON
            try:
                json.loads(content)
            except json.JSONDecodeError as e:
                messagebox.showerror("Invalid JSON",
                                     f"{rel} is not valid JSON and was not saved:\n{e}")
                return
        self.store.write(rel, content)
        self.mem_edit.edit_modified(False)
        self.mem_status.configure(text=f"saved {rel}")
        self.after(2000, lambda: self.mem_status.configure(text=""))


def _num(s, default):
    try:
        return float(s)
    except (TypeError, ValueError):
        return default


if __name__ == "__main__":
    App().mainloop()
