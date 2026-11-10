"""BlackChpok AI — MCP server (stdio).

Повна інтеграція:
  • 100% оригінальний код агента (SQLite, AST, PDF, вектори, Gemini, Auto-debug).
  • Архітектура Semantic Router (1 інструмент замість 34).
  • Вбудований браузерний агент (Playwright) для безкоштовного Gemini/DeepSeek.
"""

from __future__ import annotations

import ast
import hashlib
import json
import logging
import math
import os
import re
import select
import shutil
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.request
import urllib.parse
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Literal

# ── MCP ──────────────────────────────────────────────────────────────────────
from mcp.server.mcpserver import MCPServer

from agent_tools import AgentTools, apply_text, edits_store, self_test as router_self_test
from vibe_router import LABELS, classify, shell_plan, _looks_like_command

# ── Опційні залежності ───────────────────────────────────────────────────────
try:
    import numpy as np
    _HAS_NUMPY = True
except Exception:
    _HAS_NUMPY = False

try:
    import pymupdf as fitz
    _HAS_FITZ = True
except Exception:
    try:
        import fitz
        _HAS_FITZ = True
    except Exception:
        _HAS_FITZ = False

try:
    import pikepdf
    _HAS_PIKEPDF = True
except Exception:
    _HAS_PIKEPDF = False

try:
    from openai import OpenAI
    _HAS_OPENAI = True
except Exception:
    _HAS_OPENAI = False

try:
    from ollama import Client as OllamaClient
    _HAS_OLLAMA = True
except Exception:
    _HAS_OLLAMA = False

try:
    from rag_engine import LocalRAG
    _HAS_RAG = True
except Exception as _exc:
    _HAS_RAG = False
    _RAG_IMPORT_ERR = _exc

# ── Браузерний агент (Playwright) ────────────────────────────────────────────
try:
    from playwright.sync_api import sync_playwright
    _HAS_PLAYWRIGHT = True
except Exception:
    _HAS_PLAYWRIGHT = False

# ─────────────────────────────────────────────────────────────────────────────
# Конфігурація
# ─────────────────────────────────────────────────────────────────────────────

LOG_LEVEL = os.environ.get("MCP_LOG_LEVEL", "WARNING").upper()
logging.basicConfig(level=getattr(logging, LOG_LEVEL, logging.WARNING), format="%(asctime)s [%(levelname)s] %(name)s: %(message)s", stream=sys.stderr)
log = logging.getLogger("blackchpok-agent")

WORKSPACE_RAW = os.environ.get("MCP_WORKSPACE", "").strip()
if not WORKSPACE_RAW:
    print("FATAL: MCP_WORKSPACE не встановлено.", file=sys.stderr)
    sys.exit(1)
WORKSPACE = Path(WORKSPACE_RAW).expanduser().resolve()
DB_PATH = Path(os.environ.get("MCP_DB_PATH", str(WORKSPACE / ".mcp_rag" / "memoria_infinita.db"))).expanduser()
DB_PATH.parent.mkdir(parents=True, exist_ok=True)

LLM_BACKEND = os.environ.get("MCP_LLM_BACKEND", "auto").lower()
ENGINE_MODE = LLM_BACKEND
LMSTUDIO_URL = os.environ.get("MCP_LMSTUDIO_URL", "http://127.0.0.1:1235/v1")
LMSTUDIO_MODEL = os.environ.get("MCP_LMSTUDIO_MODEL", "ministral-3-14b-reasoning")
LMSTUDIO_API_KEY = os.environ.get("MCP_LMSTUDIO_API_KEY", "lm-studio")
OLLAMA_URL = os.environ.get("MCP_OLLAMA_URL", "http://127.0.0.1:11434")
OLLAMA_MODEL = os.environ.get("MCP_OLLAMA_MODEL", "qwen2.5-coder:14b")
OLLAMA_EMBED = os.environ.get("MCP_OLLAMA_EMBED_MODEL", "nomic-embed-text")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()
PDF_PASSWORDS = [p.strip() for p in os.environ.get("MCP_PDF_PASSWORDS", "").split(",") if p.strip()] or [""]
NUM_CTX = int(os.environ.get("MCP_NUM_CTX", "16384"))
NUM_THREAD = int(os.environ.get("MCP_NUM_THREAD", "8"))
TEMPERATURE = float(os.environ.get("MCP_TEMPERATURE", "0.15"))

MODEL_PI = "agente-pi-fast"
MODELLO_GEMINI_SCELTO = {"flash": None, "pro": None}
_BACKGROUND_PROCESSES: dict[str, subprocess.Popen] = {}
BROWSER_STATE_FILE = str(WORKSPACE / ".mcp_rag" / "browser_state.json")

# ─────────────────────────────────────────────────────────────────────────────
# ОРИГІНАЛЬНІ КОНСТАНТИ КОДУ ДРУГА
# ─────────────────────────────────────────────────────────────────────────────

REGOLA_ISTRUZIONI_LANCIO = (
    "Ogni volta che crei, salvi o spieghi uno script, alla fine dai SEMPRE istruzioni di lancio "
    "in locale sul PC Windows: comando esatto python /percorso/completo/file.py. "
    "Se è un server web (Flask/FastAPI/Streamlit) usa host 0.0.0.0 e indica l'URL."
)

CARTELLE_ESCLUSE = {
    "venv", "env", "env_finanza", "__pycache__", ".git", ".local", ".cache",
    ".ollama", "node_modules", "flutter", "build", ".dart_tool", ".config", "c",
    "site-packages", "dist-packages", "lib", "include", "bin", "share",
    ".gradle", ".idea", ".vscode", "CMakeFiles", "target", "out",
    "android", "ios", "web", "linux", "macos", "windows", ".mcp_rag",
}

MAPPA_LINGUAGGI = {
    ".py": ("CODICE", "Python"), ".cpp": ("CODICE", "C++"), ".cc": ("CODICE", "C++"),
    ".cxx": ("CODICE", "C++"), ".h": ("CODICE", "C/C++ Header"), ".hpp": ("CODICE", "C++ Header"),
    ".c": ("CODICE", "C"), ".java": ("CODICE", "Java"), ".dart": ("CODICE", "Dart / Flutter"),
    ".js": ("CODICE", "JavaScript"), ".ts": ("CODICE", "TypeScript"), ".sql": ("CODICE", "SQL Database"),
    ".sh": ("CODICE", "Bash / Shell"), ".html": ("CODICE", "HTML"), ".css": ("CODICE", "CSS"),
    ".json": ("DATI_CONFIG", "JSON Config"), ".yaml": ("DATI_CONFIG", "YAML Config"),
    ".yml": ("DATI_CONFIG", "YAML Config"), ".ini": ("DATI_CONFIG", "INI Config"),
    ".pdf": ("LIBRO", "Libro PDF"), ".epub": ("LIBRO", "Libro EPUB"),
}

PATTERN_OBSOLETI = [
    (r"\bdf\w*\.append\(", "Pandas: DataFrame.append() rimosso -> usare pd.concat()"),
    (r"asyncio\.get_event_loop\(\)", "Python: get_event_loop() deprecato -> usare asyncio.run()"),
    (r"os\.popen\(", "Python: os.popen() obsoleto -> usare subprocess.run()"),
    (r"\bauto_ptr\b|\bstd::random_shuffle\b", "C++17: rimosso -> usare std::unique_ptr / std::shuffle"),
    (r"\bgets\s*\(", "C/C++: gets() insicura -> usare fgets()"),
    (r"\bvar\s+\w+\s*=", "JS: valutare let/const al posto di var"),
]

MAPPA_PACCHETTI_PIP = {
    "cv2": "opencv-python", "PIL": "pillow", "sklearn": "scikit-learn",
    "yaml": "pyyaml", "bs4": "beautifulsoup4", "dotenv": "python-dotenv",
    "fitz": "pymupdf", "serial": "pyserial", "crypto": "pycryptodome",
    "Crypto": "pycryptodome", "telegram": "python-telegram-bot",
    "dateutil": "python-dateutil",
}

# ─────────────────────────────────────────────────────────────────────────────
# УТИЛІТИ БЕЗПЕКИ
# ─────────────────────────────────────────────────────────────────────────────

def _safe_path(raw: str, must_exist: bool = False) -> Path:
    if raw is None or str(raw).strip() == "": raw = "."
    candidate = Path(raw)
    if not candidate.is_absolute(): candidate = WORKSPACE / candidate
    resolved = candidate.expanduser().resolve()
    try: resolved.relative_to(WORKSPACE)
    except ValueError as exc: raise ValueError(f"Шлях '{raw}' поза межами MCP_WORKSPACE.") from exc
    if must_exist and not resolved.exists(): raise FileNotFoundError(f"Не існує: {resolved}")
    return resolved

def _relative(path: Path) -> str:
    try:
        posix = path.resolve().relative_to(WORKSPACE).as_posix()
        return posix if posix else "."
    except ValueError: return str(path)

def _walk_files(root: Path) -> Iterable[Path]:
    skip_dirs = {".git", ".hg", ".svn", ".mcp_rag", "node_modules", ".venv", "venv", "__pycache__", ".pytest_cache", ".mypy_cache", "dist", "build"}
    for current_root, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in skip_dirs and not d.startswith(".")]
        for name in files: yield Path(current_root) / name

def _read_text(path: Path, max_bytes: int = 5 * 1024 * 1024) -> str:
    size = path.stat().st_size
    if size > max_bytes: raise ValueError(f"Файл завеликий ({size:,} B).")
    raw = path.read_bytes()
    for enc in ("utf-8", "utf-8-sig", "cp1251", "latin-1"):
        try: return raw.decode(enc)
        except UnicodeDecodeError: continue
    return raw.decode("utf-8", errors="replace")

# ─────────────────────────────────────────────────────────────────────────────
# ОРИГІНАЛЬНІ ФУНКЦІЇ КЛАСИФІКАЦІЇ ТА AST
# ─────────────────────────────────────────────────────────────────────────────

def rileva_natura_e_linguaggio(percorso: str, contenuto_campione: str = "") -> tuple[str, str]:
    ext = os.path.splitext(percorso)[1].lower()
    if ext in MAPPA_LINGUAGGI: return MAPPA_LINGUAGGI[ext]
    c = contenuto_campione[:1000]
    if c.startswith("#!/bin/bash") or c.startswith("#!/bin/sh"): return ("CODICE", "Bash / Shell")
    if c.startswith("#!/usr/bin/env python") or ("def " in c and "import " in c): return ("CODICE", "Python")
    if "#include <" in c or "std::" in c or "int main(" in c: return ("CODICE", "C++")
    if "public class " in c or "public static void main" in c: return ("CODICE", "Java")
    if ext in {".txt", ".md"} and len(contenuto_campione) > 15000: return ("LIBRO", f"Libro Testuale ({ext})")
    return ("IGNORA", "Sconosciuto")

def rileva_lingua_umana(testo: str) -> str:
    cirillico = len(re.findall(r"[а-яА-ЯіїєґІЇЄҐ]", testo[:1500]))
    if cirillico > 20:
        if re.search(r"[іїєґІЇЄҐ]", testo[:1500]): return "UA"
        return "RU"
    return "IT"

def classifica_tema_libro(nome_file: str, testo: str) -> str:
    t = (nome_file + " " + testo[:4500]).lower()
    if any(w in t for w in ("sicurezza", "security", "hacker", "exploit", "bash", "firewall")): return "SICUREZZA_INFORMATICA"
    if any(w in t for w in ("ricco", "finanz", "trading", "econom", "invest", "denaro")): return "ECONOMIA_E_FINANZA"
    if any(w in t for w in ("matemat", "statist", "probabil", "algebra", "geometr")): return "MATEMATICA"
    if any(w in t for w in ("filosof", "etica", "mente", "psicol", "logica")): return "FILOSOFIA_E_MENTE"
    return "INFORMATICA_E_ARCHITETTURA"

def classifica_reparto_codice(percorso: str, testo: str, categoria: str) -> str:
    if categoria == "DATI_CONFIG": return "CONFIG_DATI"
    p_low = (percorso + " " + testo[:800]).lower()
    if any(w in p_low for w in ("binance", "ccxt", "trading", "quant", "market", "wallet")): return "FINANZA_QUANT"
    if any(w in p_low for w in ("scuola", "tutor", "game", "quiz", "flutter")): return "AI_EDUCAZIONE"
    if any(w in p_low for w in ("socket", "ssh", "server", "rete", "termo")): return "RETE_SISTEMI"
    return "CORE_ALGORITMI"

def scomponi_codice_multilinguaggio(percorso: str, contenuto: str, linguaggio: str) -> list[tuple[str, str, str]]:
    nodi = []
    righe = contenuto.splitlines()
    if linguaggio == "Python":
        try:
            albero = ast.parse(contenuto)
            imports = [righe[n.lineno - 1] for n in albero.body if isinstance(n, (ast.Import, ast.ImportFrom))]
            header_imp = "\n".join(imports[:10])
            for node in albero.body:
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    inizio = node.lineno - 1
                    fine = getattr(node, "end_lineno", inizio + 35)
                    blocco = "\n".join(righe[inizio:fine])
                    chiamate = {n.func.id for n in ast.walk(node) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
                    meta = f"# [Python] Import: {header_imp}\n# Chiama: {', '.join(list(chiamate)[:8])}\n"
                    tipo = "Classe_Python" if isinstance(node, ast.ClassDef) else "Algoritmo_Python"
                    nodi.append((tipo, node.name, (meta + blocco)[:1500]))
        except Exception: pass
    elif linguaggio in {"C++", "C", "C/C++ Header", "C++ Header", "Java", "Dart / Flutter", "JavaScript", "TypeScript"}:
        pattern_strutture = re.compile(r'^\s*(?:public|private|protected|static|async|virtual|inline|void|int|double|float|bool|String|Future(?:<[^>]+>)?|Widget|class|struct|function)\s+([a-zA-Z_][a-zA-Z0-9_]*)\s*[\(\{<:]', re.MULTILINE)
        matches = list(pattern_strutture.finditer(contenuto))
        for idx, m in enumerate(matches):
            nome_fn = m.group(1)
            if nome_fn in {"if", "for", "while", "switch", "catch", "return"}: continue
            pos_inizio = m.start()
            pos_fine = matches[idx + 1].start() if idx + 1 < len(matches) else pos_inizio + 1400
            blocco = contenuto[pos_inizio:min(pos_fine, pos_inizio + 1400)].strip()
            if len(blocco) > 25: nodi.append((f"Struttura_{linguaggio.split()[0]}", nome_fn, f"// [Linguaggio: {linguaggio}]\n{blocco}"))
    if not nodi and len(contenuto.strip()) > 20:
        for i in range(0, len(contenuto), 1000): nodi.append((f"Blocco_{linguaggio.split()[0]}", f"sezione_{i // 1000 + 1}", f"# [Linguaggio: {linguaggio}]\n" + contenuto[i:i + 1100]))
    return nodi

def sblocca_e_dividi_libro(percorso_file: str) -> list[tuple[str, str]]:
    blocchi: list[tuple[str, str]] = []
    if not percorso_file.lower().endswith(".pdf"):
        try:
            with open(percorso_file, "r", encoding="utf-8", errors="ignore") as f: testo = f.read()
            for i in range(0, len(testo), 950):
                pezzo = testo[i:i + 1050].strip()
                if len(pezzo) > 40: blocchi.append((f"Sez_{i // 950 + 1}", pezzo))
        except Exception: pass
        return blocchi
    if not _HAS_FITZ: return blocchi
    percorso_da_leggere = percorso_file
    file_temp: str | None = None
    try:
        doc = fitz.open(percorso_file)
        if doc.is_encrypted or not (doc.permissions & fitz.PDF_PERM_COPY):
            sbloccato = any(doc.authenticate(pwd) for pwd in PDF_PASSWORDS)
            if not sbloccato or doc.is_encrypted:
                fd, file_temp = tempfile.mkstemp(suffix=".pdf")
                os.close(fd)
                for pwd in PDF_PASSWORDS:
                    if _HAS_PIKEPDF:
                        try:
                            with pikepdf.open(percorso_file, password=pwd, allow_overwriting_input=True) as pdf_ok: pdf_ok.save(file_temp)
                            percorso_da_leggere = file_temp
                            break
                        except Exception: pass
                    if shutil.which("qpdf"):
                        # timeout обов'язковий: qpdf на зашифрованому або
                        # пошкодженому PDF може чекати пароль зі stdin і
                        # повісити весь MCP-сервер.
                        try:
                            subprocess.run(
                                ["qpdf", f"--password={pwd}", "--decrypt",
                                 percorso_file, file_temp],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                timeout=60,
                            )
                        except (subprocess.TimeoutExpired, OSError):
                            pass
                        if os.path.exists(file_temp) and os.path.getsize(file_temp) > 100:
                            percorso_da_leggere = file_temp
                            break
                doc.close()
                doc = fitz.open(percorso_da_leggere)
        for num_pag in range(len(doc)):
            t_pag = doc[num_pag].get_text("text").strip()
            if not t_pag: continue
            for sub_i in range(0, len(t_pag), 950):
                sotto = t_pag[sub_i:sub_i + 1000].strip()
                if len(sotto) > 35:
                    etichetta = f"Pag.{num_pag + 1}" if sub_i == 0 else f"Pag.{num_pag + 1}_p{sub_i // 950 + 1}"
                    blocchi.append((etichetta, sotto))
        doc.close()
    except Exception as exc: log.warning("PDF %s: %s", percorso_file, exc)
    finally:
        if file_temp and os.path.exists(file_temp):
            try: os.remove(file_temp)
            except OSError: pass
    return blocchi

# ─────────────────────────────────────────────────────────────────────────────
# ОРИГІНАЛЬНИЙ ДВИГУН (LM Studio / Ollama / Gemini)
# ─────────────────────────────────────────────────────────────────────────────

def _lmstudio_alive() -> bool:
    try:
        host = LMSTUDIO_URL.split("//", 1)[-1].split("/", 1)[0]
        hostname, _, port_s = host.partition(":")
        port = int(port_s or "1235")
        with socket.create_connection((hostname, port), timeout=1.5): return True
    except OSError: return False

def _ollama_alive() -> bool:
    try:
        host = OLLAMA_URL.split("//", 1)[-1].split("/", 1)[0]
        hostname, _, port_s = host.partition(":")
        port = int(port_s or "11434")
        with socket.create_connection((hostname, port), timeout=1.5): return True
    except OSError: return False

class _OpenAICompatibleAdapter:
    def __init__(self, client: "OpenAI", default_model: str):
        self._client = client
        self._default_model = default_model
    def chat(self, model: str | None = None, messages=None, stream: bool = True, **kwargs):
        model = model or self._default_model
        params = {"model": model, "messages": messages or [], "temperature": TEMPERATURE, "stream": stream}
        if stream:
            resp = self._client.chat.completions.create(**params)
            for chunk in resp:
                delta = chunk.choices[0].delta.content if chunk.choices else None
                if delta: yield {"message": {"content": delta}}
        else:
            resp = self._client.chat.completions.create(**params)
            yield {"message": {"content": resp.choices[0].message.content or ""}}
    def embed(self, model: str = OLLAMA_EMBED, input: str = "", **kwargs):
        try:
            resp = self._client.embeddings.create(model=model, input=input)
            return {"embeddings": [resp.data[0].embedding]}
        except Exception: return {"embeddings": [[0.0] * 768]}

class GeminiClientWrapper:
    def __init__(self, api_key: str): self.api_key = api_key
    def chat(self, model: str = "gemini-2.5-flash", messages=None, stream: bool = True, **kwargs):
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={self.api_key}"
        sys_parts, contents = [], []
        for m in (messages or []):
            ruolo = m.get("role", "user")
            testo = m.get("content", "")
            if ruolo == "system": sys_parts.append({"text": testo})
            elif ruolo == "assistant": contents.append({"role": "model", "parts": [{"text": testo}]})
            else: contents.append({"role": "user", "parts": [{"text": testo}]})
        payload = {"contents": contents, "generationConfig": {"temperature": TEMPERATURE}}
        if sys_parts: payload["systemInstruction"] = {"parts": sys_parts}
        req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=120) as resp:
            ris_json = json.loads(resp.read().decode("utf-8"))
            try: testo_out = ris_json["candidates"][0]["content"]["parts"][0]["text"]
            except Exception: testo_out = str(ris_json)
            yield {"message": {"content": testo_out}}
    def embed(self, model: str = OLLAMA_EMBED, input: str = "", **kwargs):
        if _HAS_OLLAMA:
            try: return OllamaClient(host=OLLAMA_URL).embed(model=model, input=input, truncate=True)
            except Exception: pass
        return {"embeddings": [[0.0] * 768]}

def scegli_motore(modalita_forzata: str = "auto"):
    m = (ENGINE_MODE if modalita_forzata in ("", "auto") else modalita_forzata).lower()
    if m in ("14b", "local"):
        m = "lmstudio"
    if m == "pi":
        m = "ollama"
    if m in ("gemini", "gemini-pro") and GEMINI_API_KEY:
        return (GeminiClientWrapper(GEMINI_API_KEY), "gemini-2.5-flash", "⚡ Google AI Studio")
    if m in ("auto", "lmstudio", "lm-studio", "local") and _HAS_OPENAI and _lmstudio_alive():
        client = OpenAI(base_url=LMSTUDIO_URL, api_key=LMSTUDIO_API_KEY)
        return (_OpenAICompatibleAdapter(client, LMSTUDIO_MODEL), LMSTUDIO_MODEL, f"🧠 LM Studio ({LMSTUDIO_MODEL})")
    if _HAS_OLLAMA and (_ollama_alive() or m in ("auto", "ollama")):
        return (OllamaClient(host=OLLAMA_URL), OLLAMA_MODEL, f"🦙 Ollama ({OLLAMA_MODEL})")
    if GEMINI_API_KEY:
        return (GeminiClientWrapper(GEMINI_API_KEY), "gemini-2.5-flash", "⚡ Google AI Studio (fallback)")
    raise RuntimeError("Жоден LLM-двигун недоступний.")
    # ─────────────────────────────────────────────────────────────────────────────
# БАЗА ДАНИХ ТА ВЕКТОРИ (ПОВНІСТЮ З КОДУ ДРУГА)
# ─────────────────────────────────────────────────────────────────────────────

def init_db() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH), timeout=30)
    c = conn.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS fatti_permanenti (id INTEGER PRIMARY KEY AUTOINCREMENT, fatto TEXT, reparto TEXT DEFAULT 'GENERALE', data TEXT)""")
    c.execute("""CREATE VIRTUAL TABLE IF NOT EXISTS storico_chat USING fts5(ruolo, contenuto, data)""")
    c.execute("""CREATE TABLE IF NOT EXISTS rete_codice (id INTEGER PRIMARY KEY AUTOINCREMENT, percorso TEXT, progetto TEXT, linguaggio TEXT, reparto TEXT, tipo_nodo TEXT, nome_oggetto TEXT, codice TEXT, stato_validita TEXT, livello_uso TEXT, valore_strategico TEXT, complessita TEXT, note_obsolescenza TEXT, usi_contatore INTEGER DEFAULT 0, ultimo_uso TEXT, mtime REAL, vettore TEXT)""")
    c.execute("""CREATE TABLE IF NOT EXISTS biblioteca_libri (id INTEGER PRIMARY KEY AUTOINCREMENT, titolo_libro TEXT, percorso TEXT, file_hash TEXT, tema_principale TEXT, lingua TEXT, sezione_pagine TEXT, concetto_testo TEXT, stato_validita TEXT, livello_uso TEXT, usi_contatore INTEGER DEFAULT 0, mtime REAL, vettore TEXT)""")
    c.execute("""CREATE TABLE IF NOT EXISTS lezioni_imparate (id INTEGER PRIMARY KEY AUTOINCREMENT, progetto_o_libro TEXT UNIQUE, categoria TEXT, linguaggi_rilevati TEXT, tema_o_reparto TEXT, riassunto_studio TEXT, regole_linguaggio_e_logica TEXT, data_studio TEXT)""")
    c.execute("""CREATE INDEX IF NOT EXISTS idx_codice_veloce ON rete_codice (reparto, linguaggio, stato_validita, livello_uso)""")
    c.execute("""CREATE INDEX IF NOT EXISTS idx_libri_veloce ON biblioteca_libri (tema_principale, stato_validita, livello_uso)""")
    c.execute("SELECT fatto FROM fatti_permanenti")
    fatti_esistenti = [r[0] for r in c.fetchall()]
    if not any("istruzioni di lancio" in (f or "").lower() for f in fatti_esistenti):
        c.execute("INSERT INTO fatti_permanenti (fatto, data) VALUES (?, ?)", (REGOLA_ISTRUZIONI_LANCIO, datetime.now().strftime("%Y-%m-%d %H:%M")))
    conn.commit()
    return conn

def calcola_hash_file(percorso: str | Path) -> str:
    h = hashlib.md5()
    try:
        with open(percorso, "rb") as f:
            while chunk := f.read(65536): h.update(chunk)
        return h.hexdigest()
    except Exception: return str(percorso)

def calcola_vettore(client_preferito, testo: str) -> list[float]:
    if _rag is not None and os.environ.get("MCP_RAG_EMBEDDINGS_URL", "").strip():
        vectors = _rag._embed_batch([testo[:1200]])
        if vectors:
            return list(vectors[0])
    for lunghezza in (1200, 700, 400):
        frammento = testo[:lunghezza]
        try:
            res = client_preferito.embed(model=OLLAMA_EMBED, input=frammento, truncate=True)
            if isinstance(res, dict) and res.get("embeddings"): return list(res["embeddings"][0])
        except Exception: pass
    return [0.0] * 768

def genera_sintesi_libro(client_llm, modello_llm: str, titolo: str, tema: str, lingua: str, estratti: str) -> str:
    sys_libro = "Sei un Pensatore Universale... Analizza libri di qualsiasi argomento."
    prompt = f"Analizza questi estratti del libro '{titolo}' (Tema: {tema} | Lingua: {lingua}):\n{estratti[:3500]}\n\nEsponi in Italiano una sintesi profonda in 4 punti."
    risp = ""
    try:
        for chunk in client_llm.chat(model=modello_llm, messages=[{"role": "system", "content": sys_libro}, {"role": "user", "content": prompt}], stream=True, options=opzioni_ottimali_modello(modello_llm)):
            risp += chunk["message"]["content"]
    except Exception as exc: log.warning("sintesi libro: %s", exc)
    return risp

def genera_sintesi_codice(client_llm, modello_llm: str, nome_prog: str, reparto: str, linguaggi_str: str, estratti: str, note_obs: str) -> str:
    sys_cod = "Sei un Architetto Software Poliglotta... Analizza con precisione chirurgica il codice."
    prompt = f"Progetto '{nome_prog}' (Reparto: {reparto} | Linguaggi: {linguaggi_str}).\nEstratti:\n{estratti[:3200]}\nNote obsolescenza: {note_obs}\n\nRiassumi in 4 punti."
    risp = ""
    try:
        for chunk in client_llm.chat(model=modello_llm, messages=[{"role": "system", "content": sys_cod}, {"role": "user", "content": prompt}], stream=True, options=opzioni_ottimali_modello(modello_llm)):
            risp += chunk["message"]["content"]
    except Exception as exc: log.warning("sintesi codice: %s", exc)
    return risp

def indicizza_interattivo(conn: sqlite3.Connection, cartella_base: str) -> str:
    cartella_base = str(_safe_path(cartella_base, must_exist=True))
    client_llm, modello_llm, hw_label = scegli_motore("auto")
    c = conn.cursor()
    c.execute("SELECT DISTINCT file_hash FROM biblioteca_libri")
    hash_libri_studiati = {r[0] for r in c.fetchall() if r[0]}
    c.execute("SELECT percorso, MAX(mtime) FROM rete_codice GROUP BY percorso")
    mappa_mtime = {r[0]: r[1] for r in c.fetchall() if r[0]}
    da_studiare: dict[str, list[tuple[str, str, float, str, str]]] = {}
    hash_visti: set[str] = set()

    for root, dirs, files in os.walk(cartella_base):
        dirs[:] = [d for d in dirs if d not in CARTELLE_ESCLUSE and not d.startswith(".")]
        if "backup" in root.lower(): continue
        for file in files:
            percorso_completo = os.path.join(root, file)
            try:
                ext = os.path.splitext(file)[1].lower()
                if ext not in MAPPA_LINGUAGGI: continue
                categoria_file, nome_linguaggio = MAPPA_LINGUAGGI[ext]
                dim_file = os.path.getsize(percorso_completo)
                if categoria_file == "DATI_CONFIG" and dim_file > 100000: continue
                if categoria_file == "CODICE" and dim_file > 400000: continue
                mtime = os.path.getmtime(percorso_completo)
                rel_path = os.path.relpath(percorso_completo, cartella_base)
                if categoria_file == "LIBRO":
                    f_hash = calcola_hash_file(percorso_completo)
                    if f_hash in hash_libri_studiati or f_hash in hash_visti: continue
                    hash_visti.add(f_hash)
                    gruppo = f"LIBRO: {file}"
                else:
                    old_mtime = mappa_mtime.get(rel_path)
                    if old_mtime is not None and abs(old_mtime - mtime) < 1.0: continue
                    parti = rel_path.split(os.sep)
                    gruppo = "CB_" + parti[1] if (parti[0] == "progetti_chromebook" and len(parti) > 1) else parti[0]
                da_studiare.setdefault(gruppo, []).append((percorso_completo, rel_path, mtime, categoria_file, nome_linguaggio))
            except Exception: pass

    if not da_studiare: return "✅ Все вже актуально."
    log_summary: list[str] = []
    for gruppo, lista_file in da_studiare.items():
        is_libro = gruppo.startswith("LIBRO:")
        if is_libro:
            percorso_completo, rel_path, mtime, _, _ = lista_file[0]
            titolo = os.path.basename(percorso_completo)
            f_hash = calcola_hash_file(percorso_completo)
            blocchi_libro = sblocca_e_dividi_libro(percorso_completo)
            if not blocchi_libro: continue
            passo = max(1, len(blocchi_libro) // 8)
            campioni = [blocchi_libro[i][1] for i in range(0, len(blocchi_libro), passo)][:8]
            testo_campione = "\n---\n".join(campioni)
            tema = classifica_tema_libro(titolo, testo_campione)
            lingua = rileva_lingua_umana(testo_campione)
            c.execute("DELETE FROM biblioteca_libri WHERE file_hash = ?", (f_hash,))
            for etichetta_pag, testo_concetto in blocchi_libro:
                prompt_emb = f"Libro: {titolo} | Tema: {tema} | {etichetta_pag}\n{testo_concetto}"
                vettore = calcola_vettore(client_llm, prompt_emb)
                c.execute("""INSERT INTO biblioteca_libri (titolo_libro, percorso, file_hash, tema_principale, lingua, sezione_pagine, concetto_testo, stato_validita, livello_uso, usi_contatore, mtime, vettore) VALUES (?, ?, ?, ?, ?, ?, ?, 'ATTIVO', 'WARM', 0, ?, ?)""", (titolo, rel_path, f_hash, tema, lingua, etichetta_pag, testo_concetto, mtime, json.dumps(vettore)))
            conn.commit()
            riassunto_l = genera_sintesi_libro(client_llm, modello_llm, titolo, tema, lingua, testo_campione)
            c.execute("""INSERT OR REPLACE INTO lezioni_imparate (progetto_o_libro, categoria, linguaggi_rilevati, tema_o_reparto, riassunto_studio, regole_linguaggio_e_logica, data_studio) VALUES (?, 'LIBRO_LOGICA', ?, ?, ?, ?, ?)""", (titolo, f"Libro ({lingua})", tema, riassunto_l, f"Logica {tema}", datetime.now().strftime("%Y-%m-%d %H:%M")))
            conn.commit()
            log_summary.append(f"[LIBRO] {titolo} -> {len(blocchi_libro)} блоків")
        else:
            estratti_cod: list[str] = []
            problemi_obs: list[str] = []
            reparto_p = "CORE_ALGORITMI"
            tot_nodi = 0
            linguaggi_usati: set[str] = set()
            for percorso_completo, rel_path, mtime, cat_f, nome_ling in lista_file:
                linguaggi_usati.add(nome_ling)
                try:
                    with open(percorso_completo, "r", encoding="utf-8", errors="ignore") as f: contenuto = f.read()
                except Exception: continue
                if not contenuto.strip(): continue
                nodi = scomponi_codice_multilinguaggio(percorso_completo, contenuto, nome_ling)
                c.execute("DELETE FROM rete_codice WHERE percorso = ?", (rel_path,))
                for tipo, nome_obj, blocco in nodi:
                    reparto_p = classifica_reparto_codice(rel_path, blocco, cat_f)
                    avvisi = [msg for reg, msg in PATTERN_OBSOLETI if re.search(reg, blocco)]
                    st_val = "DA_AGGIORNARE" if avvisi else "ATTIVO"
                    note_o = " | ".join(avvisi) if avvisi else "Valido"
                    if avvisi: problemi_obs.append(f"[{rel_path} ({nome_ling}) -> {nome_obj}]: {note_o}")
                    compl = "ALTA" if len(blocco.splitlines()) > 35 else "MEDIA"
                    val_st = "CRITICO" if compl == "ALTA" else "STANDARD"
                    vettore = calcola_vettore(client_llm, f"Linguaggio: {nome_ling} | Reparto: {reparto_p} | {nome_obj}\n{blocco}")
                    c.execute("""INSERT INTO rete_codice (percorso, progetto, linguaggio, reparto, tipo_nodo, nome_oggetto, codice, stato_validita, livello_uso, valore_strategico, complessita, note_obsolescenza, usi_contatore, ultimo_uso, mtime, vettore) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'WARM', ?, ?, ?, 0, ?, ?, ?)""", (rel_path, gruppo, nome_ling, reparto_p, tipo, nome_obj, blocco, st_val, val_st, compl, note_o, datetime.now().strftime("%Y-%m-%d"), mtime, json.dumps(vettore)))
                    tot_nodi += 1
                    if len(estratti_cod) < 6: estratti_cod.append(f"--- [{nome_ling}] {rel_path} ({nome_obj}) ---\n{blocco[:500]}")
                conn.commit()
            if tot_nodi > 0:
                str_prob = "\n".join(problemi_obs) if problemi_obs else "Codice attuale e ben strutturato."
                str_ling = ", ".join(sorted(linguaggi_usati))
                riassunto_c = genera_sintesi_codice(client_llm, modello_llm, gruppo, reparto_p, str_ling, "\n".join(estratti_cod), str_prob)
                c.execute("""INSERT OR REPLACE INTO lezioni_imparate (progetto_o_libro, categoria, linguaggi_rilevati, tema_o_reparto, riassunto_studio, regole_linguaggio_e_logica, data_studio) VALUES (?, 'PROGETTO_MULTILINGUAGGIO', ?, ?, ?, ?, ?)""", (gruppo, str_ling, reparto_p, riassunto_c, str_prob, datetime.now().strftime("%Y-%m-%d %H:%M")))
                conn.commit()
                log_summary.append(f"[PROGETTO] {gruppo} -> {tot_nodi} вузлів ({str_ling})")
    return "\n".join(log_summary) if log_summary else "Готово (без змін)."

def cerca_cognitiva_doppia(conn: sqlite3.Connection, query_utente: str) -> tuple[str, str]:
    if not _HAS_NUMPY: return "", ""
    c = conn.cursor()
    try: client_embed, _, _ = scegli_motore("auto")
    except Exception: return "", ""
    v_query = np.array(calcola_vettore(client_embed, query_utente), dtype=np.float32)
    norm_q = float(np.linalg.norm(v_query))
    if norm_q == 0: return "", ""
    c.execute("SELECT id, titolo_libro, tema_principale, lingua, sezione_pagine, concetto_testo, usi_contatore, vettore FROM biblioteca_libri WHERE stato_validita != 'OBSOLETO'")
    ris_libri = []
    for id_l, tit, tema, ling, pag, testo, usi, v_json in c.fetchall():
        try: v_n = np.array(json.loads(v_json), dtype=np.float32)
        except Exception: continue
        sim = float(np.dot(v_query, v_n) / (norm_q * np.linalg.norm(v_n) + 1e-9))
        ris_libri.append((sim, id_l, tit, tema, ling, pag, testo, usi))
    ris_libri.sort(key=lambda x: x[0], reverse=True)
    estratti_libri: list[str] = []
    for sim, id_l, tit, tema, ling, pag, testo, usi in ris_libri[:3]:
        if sim > 0.38:
            estratti_libri.append(f"📘 [LIBRO: {tit} | TEMA: {tema} ({ling}) | {pag}]\n{testo}")
            c.execute("UPDATE biblioteca_libri SET usi_contatore = ?, livello_uso = ? WHERE id = ?", (usi + 1, "HOT" if usi + 1 >= 3 else "WARM", id_l))
    c.execute("SELECT id, linguaggio, reparto, progetto, percorso, nome_oggetto, codice, stato_validita, note_obsolescenza, usi_contatore, vettore FROM rete_codice WHERE stato_validita != 'OBSOLETO'")
    ris_cod = []
    for (id_c, ling_p, rep, prog, perc, nome, cod, st_val, note_o, usi, v_json) in c.fetchall():
        try: v_n = np.array(json.loads(v_json), dtype=np.float32)
        except Exception: continue
        sim = float(np.dot(v_query, v_n) / (norm_q * np.linalg.norm(v_n) + 1e-9))
        bonus = 0.05 if usi >= 3 else 0.0
        ris_cod.append((sim + bonus, id_c, ling_p, rep, prog, perc, nome, cod, st_val, note_o, usi))
    ris_cod.sort(key=lambda x: x[0], reverse=True)
    estratti_codice: list[str] = []
    for sim, id_c, ling_p, rep, prog, perc, nome, cod, st_val, note_o, usi in ris_cod[:4]:
        if sim > 0.40:
            avv = f"\n⚠️ [NOTA OBSOLESCENZA: {note_o}]" if st_val == "DA_AGGIORNARE" else ""
            estratti_codice.append(f"💻 [LINGUAGGIO: {ling_p} | REPARTO: {rep} | Progetto: {prog} -> {perc} ({nome})]{avv}\n```\n{cod}\n```")
            c.execute("UPDATE rete_codice SET usi_contatore = ?, livello_uso = ? WHERE id = ?", (usi + 1, "HOT" if usi + 1 >= 3 else "WARM", id_c))
    conn.commit()
    return "\n".join(estratti_libri).strip(), "\n".join(estratti_codice).strip()

def carica_ultimi_messaggi_ssd(conn: sqlite3.Connection, limite: int = 10) -> list[dict]:
    c = conn.cursor()
    c.execute("SELECT ruolo, contenuto, data FROM storico_chat ORDER BY rowid DESC LIMIT ?", (limite,))
    righe = c.fetchall()[::-1]
    sessione: list[dict] = []
    for ruolo, cont, data in righe:
        r_api = "user" if ruolo == "Utente" else "assistant"
        sessione.append({"role": r_api, "content": f"[{data}] {cont[:1200]}"})
    return sessione

def cerca_nello_storico_chat(conn: sqlite3.Connection, query_utente: str) -> str:
    c = conn.cursor()
    c.execute("SELECT ruolo, contenuto, data FROM storico_chat ORDER BY rowid DESC LIMIT 6")
    ultimi = [f"• [{r[2]}] {r[0]}: {r[1][:500]}" for r in c.fetchall()[::-1]]
    parole = [p for p in re.findall(r"\w+", query_utente) if len(p) > 3 and p.lower() not in {"ricordi", "ultimo", "codice", "python"}]
    ricordi_fts: list[str] = []
    if parole:
        q_fts = " OR ".join(f'"{p}"' for p in parole[:5])
        try:
            c.execute("SELECT ruolo, contenuto, data FROM storico_chat WHERE storico_chat MATCH ? ORDER BY rank LIMIT 4", (q_fts,))
            ricordi_fts = [f"• [{r[2]}] {r[0]}: {r[1][:500]}" for r in c.fetchall()]
        except Exception: pass
    combinati = ultimi + [r for r in ricordi_fts if r not in ultimi]
    return "\n".join(combinati[:8])

def controlla_e_installa_libreria(stderr_text: str, auto_yes: bool = False) -> bool:
    match = re.search(r"ModuleNotFoundError: No module named ['\"]([^'\"]+)['\"]", stderr_text)
    if not match: return False
    modulo_base = match.group(1).split(".")[0]
    pacchetto = MAPPA_PACCHETTI_PIP.get(modulo_base, modulo_base)
    log.info("Відсутня бібліотека: %s -> pip install %s", modulo_base, pacchetto)
    if auto_yes:
        # timeout: pip може чекати мережу або заблокований файл нескінченно,
        # а це вже з'єднання з клієнтом — воно має відповісти.
        try:
            ris = subprocess.run(
                [sys.executable, "-m", "pip", "install", pacchetto],
                capture_output=True, text=True, timeout=600,
            )
            return ris.returncode == 0
        except (subprocess.TimeoutExpired, OSError):
            log.warning("pip install %s не завершився за 600 с", pacchetto)
            return False
    return False

def verifica_server_web_locale(percorso_file: str) -> str | None:
    try:
        with open(percorso_file, "r", encoding="utf-8", errors="ignore") as f: c_txt = f.read()
    except Exception: return None
    if not any(x in c_txt.lower() for x in ("flask", "fastapi", "app.run")): return None
    porte = re.findall(r"port\s*=\s*(\d+)", c_txt)
    porta = porte[-1] if porte else "5000"
    proc = subprocess.Popen([sys.executable, percorso_file], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    errore_http: str | None = None
    err_srv = ""
    try:
        time.sleep(2.5)
        if proc.poll() is None:
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{porta}/", timeout=4) as r:
                    html_letto = r.read().decode("utf-8", errors="ignore")
                    if len(html_letto.strip()) < 20: errore_http = "HTML vuoto."
                    elif "In attesa dei dati" in html_letto: errore_http = "Thread bloccato."
            except Exception as e_url: errore_http = f"Errore http://127.0.0.1:{porta}/ -> {e_url}"
    finally:
        proc.terminate()
        try:
            out_srv, err_srv = proc.communicate(timeout=2)
            err_srv = (out_srv or "") + "\n" + (err_srv or "")
        except Exception: proc.kill()
    if errore_http or "Traceback" in err_srv or "Exception on" in err_srv:
        return f"{errore_http or ''}\n{err_srv}".strip()
    return None

def esegui_e_ripara_codice(client, modello_attivo: str, hardware_attivo: str, percorso_file: str, max_tentativi: int = 3) -> str:
    percorso_file = str(_safe_path(percorso_file, must_exist=True))
    if not os.path.isfile(percorso_file): return "Файл не знайдено."
    log_parts: list[str] = []
    for tentativo in range(1, max_tentativi + 1):
        log_parts.append(f"Спроба {tentativo}/{max_tentativi}: {percorso_file}")
        try:
            ris = subprocess.run([sys.executable, percorso_file], capture_output=True, text=True, timeout=15)
            stdout, stderr, exit_code = ris.stdout.strip(), ris.stderr.strip(), ris.returncode
        except subprocess.TimeoutExpired as e:
            out_parz = (e.stdout.decode("utf-8", errors="ignore") if isinstance(e.stdout, bytes) else (e.stdout or "")).strip()
            err_parz = (e.stderr.decode("utf-8", errors="ignore") if isinstance(e.stderr, bytes) else (e.stderr or "")).strip()
            if "Traceback" not in err_parz and "Error:" not in err_parz:
                err_web = verifica_server_web_locale(percorso_file)
                if err_web: stderr, exit_code = err_web, 1
                else: return "✅ Сервер працює (timeout = нормально для Flask/FastAPI)."
            else: stderr, exit_code = err_parz, 1
        if exit_code == 0: return f"✅ Успіх.\n{stdout[:2000]}"
        log_parts.append(f"⚠️ stderr:\n{stderr[-800:]}")
        if controlla_e_installa_libreria(stderr, auto_yes=True):
            log_parts.append("📦 Спробував авто-встановити pip-пакет.")
            continue
        try:
            with open(percorso_file, "r", encoding="utf-8") as f: codice_attuale = f.read()
        except Exception: return "Не вдалося прочитати файл."
        prompt_fix = f"Il file '{percorso_file}' ha generato questo errore:\n```\n{stderr}\n```\n\nCodice attuale:\n```python\n{codice_attuale}\n```\nCorreggi il bug e restituisci SOLO l'intero file Python corretto tra ```python e ```."
        risposta_fix = ""
        try:
            for chunk in client.chat(model=modello_attivo, messages=[{"role": "system", "content": "Sei un motore di Auto-Debugging."}, {"role": "user", "content": prompt_fix}], stream=True, options=opzioni_ottimali_modello(modello_attivo)):
                risposta_fix += chunk["message"]["content"]
        except Exception as exc:
            log_parts.append(f"LLM-fix error: {exc}")
            break
        blocchi = re.findall(r"```(?:python)?\n(.*?)```", risposta_fix, re.DOTALL)
        if blocchi:
            nuovo_codice = "\n\n".join(blocchi)
            diff = apply_text(Path(percorso_file), nuovo_codice + "\n", _relative, edits_store(DB_PATH))
            log_parts.append("Патч застосовано, копія .bak поруч. Повторюю.\n" + diff[:900])
        else:
            log_parts.append("LLM не повернув код у ```python ... ``` — стоп.")
            break
    return "\n".join(log_parts)

def opzioni_ottimali_modello(modello: str) -> dict[str, Any]:
    return {"num_ctx": NUM_CTX, "num_thread": NUM_THREAD, "temperature": TEMPERATURE}

# ─────────────────────────────────────────────────────────────────────────────
# ВБУДОВАНИЙ БРАУЗЕРНИЙ АГЕНТ (PLAYWRIGHT)
# ─────────────────────────────────────────────────────────────────────────────

def do_ask_browser_ai(prompt: str, provider: str = "gemini") -> str:
    """Відкриває браузер, надсилає запит до Gemini/DeepSeek та повертає відповідь."""
    if not _HAS_PLAYWRIGHT:
        return "Помилка: Playwright не встановлено. Виконайте 'pip install playwright' та 'playwright install chromium'."

    if not os.path.exists(BROWSER_STATE_FILE):
        return "⚠️ Сесія браузера не знайдена. Запустіть 'setup_browser.py' для входу."

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=False) 
            context = browser.new_context(storage_state=BROWSER_STATE_FILE)
            page = context.new_page()

            if provider == "gemini":
                page.goto("https://gemini.google.com/app", timeout=60000)
                page.wait_for_timeout(3000) 
                input_box = page.locator("div[contenteditable='true']").first
                if not input_box.is_visible():
                    return "Не вдалося знайти поле вводу в Gemini."
                input_box.fill(prompt)
                page.keyboard.press("Enter")
                page.wait_for_timeout(8000) 
                response_blocks = page.locator("message-content").all()
                if not response_blocks:
                    return "Не вдалося знайти відповідь від Gemini."
                last_response = response_blocks[-1].inner_text()
                return f"🤖 Відповідь від {provider}:\n\n{last_response}"

            elif provider == "deepseek":
                page.goto("https://chat.deepseek.com/", timeout=60000)
                page.wait_for_timeout(3000)
                input_box = page.locator("textarea").first
                if not input_box.is_visible():
                    return "Не вдалося знайти поле вводу в DeepSeek."
                input_box.fill(prompt)
                page.keyboard.press("Enter")
                page.wait_for_timeout(8000)
                response_blocks = page.locator(".ds-markdown").all()
                if not response_blocks:
                    return "Не вдалося знайти відповідь від DeepSeek."
                last_response = response_blocks[-1].inner_text()
                return f"🤖 Відповідь від {provider}:\n\n{last_response}"
            else:
                return f"Провайдер '{provider}' не підтримується."
    except Exception as e:
        return f"Помилка браузера: {type(e).__name__}: {e}"
    finally:
        # Голий ``except`` тут глушив і переривання, і SystemExit: закриття
        # браузера не має ламати результат виклику, але й не має ковтати
        # такі винятки мовчки.
        try:
            browser.close()
        except Exception:  # noqa: BLE001 - прибирання не має кидати далі
            pass


# ─────────────────────────────────────────────────────────────────────────────
# RAG-Шар
# ─────────────────────────────────────────────────────────────────────────────

if _HAS_RAG:
    _rag = LocalRAG(root=WORKSPACE, safe_path=_safe_path, walk_files=_walk_files, read_text=_read_text, relative_path=_relative)
else:
    _rag = None

# ─────────────────────────────────────────────────────────────────────────────
# ГОЛОВНИЙ MCP СЕРВЕР ТА РОУТЕР
# ─────────────────────────────────────────────────────────────────────────────

_MEMORY_SYNCED = False

def sync_long_memory() -> int:
    global _MEMORY_SYNCED
    if _rag is None:
        return 0
    if _MEMORY_SYNCED:
        return 0
    items: list[tuple[str, str]] = []
    try:
        conn = init_db()
        try:
            items.extend(("rule", row[0] or "") for row in conn.execute("SELECT fatto FROM fatti_permanenti"))
            items.extend(
                ("chat", f"[{row[2]}] {row[0]}: {row[1] or ''}")
                for row in conn.execute("SELECT ruolo, contenuto, data FROM storico_chat ORDER BY rowid DESC LIMIT 80")
            )
            items.extend(
                ("lesson", f"{row[0]}: {row[1] or ''}")
                for row in conn.execute("SELECT progetto_o_libro, riassunto_studio FROM lezioni_imparate")
            )
        finally:
            conn.close()
        saved = _rag.remember_many(items)
        _rag.refresh_memory(force=True)
        _MEMORY_SYNCED = True
        return saved
    except Exception as exc:
        log.warning("синхронізація пам'яті: %s", exc)
        return 0


def do_index_project(raw: str, phrase: str) -> str:
    if _rag is None:
        return "Локальний RAG не зібрано."
    target = (raw or ".").strip() or "."
    report_raw = _rag.index_workspace(target)
    try:
        report = json.loads(report_raw)
    except json.JSONDecodeError:
        return report_raw
    saved = sync_long_memory()
    symbols = _TOOLS.index_symbols(target)
    lines = [
        symbols,
        f"Пам'ять оновлено. Змінених файлів: {report.get('files_indexed_or_updated', 0)}. Без змін: {report.get('files_unchanged', 0)}.",
        f"В індексі {report.get('documents_total_in_index', 0)} файлів, {report.get('chunks_total_in_index', 0)} фрагментів, з векторами {report.get('chunks_with_embeddings_total', 0)}.",
        f"Режим: {report.get('retrieval_mode', '')}. Розмов і правил додано зараз: {saved}.",
    ]
    errors = report.get("errors") or []
    if errors:
        lines.append("Не вдалося прочитати: " + "; ".join(str(item) for item in errors[:5]))
    if any(word in (phrase or "").lower() for word in ("книг", "глибок", "pdf", "урок")):
        conn = init_db()
        try:
            lines.append(indicizza_interattivo(conn, target))
        finally:
            conn.close()
    return "\n".join(lines)


def _log_hit(phrase: str, intent: str, file_path: str) -> None:
    try:
        path = DB_PATH.parent / "vibe_hits.log"
        row = {
            "at": datetime.now().isoformat(timespec="seconds"),
            "phrase": phrase[:400],
            "intent": intent,
            "path": file_path,
            "weak": intent == "talk",
        }
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    except Exception as exc:
        log.warning("журнал влучень: %s", exc)


def _memory_footer() -> str:
    rules = ""
    recent = ""
    try:
        conn = init_db()
        try:
            rules = " | ".join(
                (row[0] or "").replace("\n", " ")[:140]
                for row in conn.execute("SELECT fatto FROM fatti_permanenti ORDER BY id DESC LIMIT 4")
            )
            recent_rows = conn.execute(
                "SELECT ruolo, contenuto FROM storico_chat ORDER BY rowid DESC LIMIT 3"
            ).fetchall()
            recent = " | ".join(
                f"{row[0]}: {(row[1] or '').replace(chr(10), ' ')[:120]}" for row in reversed(recent_rows)
            )
        finally:
            conn.close()
    except Exception as exc:
        log.warning("пам'ять у відповіді: %s", exc)
    embed_model = os.environ.get("MCP_RAG_EMBEDDINGS_MODEL", "").strip() or "text-embedding-nomic-embed-text-v1.5"
    embed_url = os.environ.get("MCP_RAG_EMBEDDINGS_URL", "").strip()
    vector = f"Вектори: {embed_model}" + (f" @ {embed_url}" if embed_url else " (немає MCP_RAG_EMBEDDINGS_URL)")
    rag_line = ""
    if _rag is not None:
        try:
            info = json.loads(_rag.status())
            rag_line = (
                f"RAG: {info.get('documents', 0)} файлів, "
                f"векторів {info.get('chunks_with_embeddings', 0)}, "
                f"записів пам'яті {info.get('memories', 0)}."
            )
        except Exception:
            rag_line = ""
    project_line = ""
    symbol_line = ""
    try:
        brief = _TOOLS.notes_brief()
        if brief:
            project_line = f"Проєкт: {brief}"
        symbol_line = f"Символів у локальному індексі: {_TOOLS.symbol_count()}."
    except Exception:
        project_line = ""
        symbol_line = ""
    return "\n".join(part for part in (
        "--- пам'ять ---",
        f"Правила: {rules}" if rules else "",
        f"Недавнє: {recent}" if recent else "",
        project_line,
        symbol_line,
        vector,
        rag_line,
    ) if part)


def _fit(text: str, limit: int = 4500) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n… обрізано, ще {len(text) - limit} символів. Попроси вужчий діапазон."


def _remember(user_text: str, agent_text: str) -> None:
    try:
        conn = init_db()
        ora = datetime.now().strftime("%Y-%m-%d %H:%M")
        conn.execute("INSERT INTO storico_chat (ruolo, contenuto, data) VALUES (?, ?, ?)", ("Utente", user_text[:2000], ora))
        conn.execute("INSERT INTO storico_chat (ruolo, contenuto, data) VALUES (?, ?, ?)", ("Agente", agent_text[:2000], ora))
        conn.commit()
        conn.close()
    except Exception as exc:
        log.warning("історія чату: %s", exc)
    if _rag is not None:
        _rag.remember(f"Користувач: {user_text[:700]}\nАгент: {agent_text[:700]}", "chat")

def do_memory_search(query: str) -> str:
    parts: list[str] = []
    if _rag is not None:
        sync_long_memory()
        try:
            note = _TOOLS.refresh_stored_facts()
            if "Прибрано застарілих: 0." not in note or "застарілих записів: 0" not in note:
                parts.append(note)
        except Exception as exc:
            log.warning("звірка пам'яті: %s", exc)
        parts.append(_rag.recall(query))
    conn = init_db()
    try:
        books, code = cerca_cognitiva_doppia(conn, query)
    except Exception as exc:
        log.warning("когнітивний пошук: %s", exc)
        books, code = "", ""
    finally:
        conn.close()
    if books:
        parts.append(books)
    if code:
        parts.append(code)
    return "\n\n".join(part for part in parts if part) or "У довгостроковій пам'яті нічого схожого."

def do_chat_history(query: str) -> str:
    conn = init_db()
    try:
        return cerca_nello_storico_chat(conn, query) or "Історія розмов порожня."
    finally:
        conn.close()

def do_talk(query: str) -> str:
    conn = init_db()
    try:
        rules = "\n".join(f"- {row[0]}" for row in conn.execute("SELECT fatto FROM fatti_permanenti ORDER BY id DESC LIMIT 12"))
        history = cerca_nello_storico_chat(conn, query)
    finally:
        conn.close()
    parts = ["Це розмова, окрема файлова дія не потрібна."]
    if rules:
        parts.append("Правила:\n" + rules)
    if history:
        parts.append("Недавні репліки:\n" + history)
    return "\n\n".join(parts)

def do_set_engine(mode: str) -> str:
    global ENGINE_MODE
    allowed = {"auto", "lmstudio", "ollama", "gemini", "gemini-pro"}
    picked = (mode or "auto").strip().lower()
    if picked not in allowed:
        return f"Невідомий режим '{picked}'. Можна: {', '.join(sorted(allowed))}."
    ENGINE_MODE = picked
    try:
        _client, model, label = scegli_motore(picked)
        return f"Режим {picked}. Зараз відповідає {label}."
    except Exception as exc:
        return f"Режим збережено як {picked}, але двигун зараз недоступний: {exc}"

def do_cli(phrase: str, query: str, extra: str) -> str:
    command = query.strip() if _looks_like_command(query) else ""
    if not command:
        command = shell_plan(phrase or query)
    if not command:
        return "Не зрозумів, що зробити в терміналі. Можна сказати: яка версія git, чи є node, встанови requests."
    result = _TOOLS.run_shell(command, extra or "180")
    hint = ""
    lowered = result.lower()
    if "is not recognized" in lowered or "не є внутрішньою" in lowered or "не распознан" in lowered:
        hint = "\nЦієї команди немає в PATH. Наступним кроком скажи, що саме встановити."
    return f"$ {command}\n{result}{hint}"


def do_install_package(name: str) -> str:
    package = (name or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9_.\-]+", package):
        return "Назви пакет одним словом, наприклад requests."
    proc = subprocess.run([sys.executable, "-m", "pip", "install", package], capture_output=True, text=True, timeout=180)
    tail = ((proc.stdout or "") + (proc.stderr or ""))[-1500:]
    if proc.returncode == 0:
        return f"Встановлено {package}.\n{tail}"
    return f"pip завершився з кодом {proc.returncode}.\n{tail}"

def do_project_context(raw: str) -> str:
    path = _safe_path(raw or ".", must_exist=True)
    folder = path if path.is_dir() else path.parent
    names = [path.name, "templates/index.html", "static/style.css", "README.md"]
    if path.is_file():
        names.insert(0, path.name)
    chunks = []
    for name in names:
        candidate = folder / name if name != path.name or path.is_dir() else path
        if name == path.name and path.is_file():
            candidate = path
        if not candidate.is_file():
            continue
        text = _read_text(candidate)[:4000]
        chunks.append(f"--- {_relative(candidate)} ---\n{text}")
    return "\n\n".join(chunks) or "Поруч немає файлів для контексту."

def ip_lan_locale() -> str:
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(1)
        sock.connect(("8.8.8.8", 80))
        ip = sock.getsockname()[0]
        sock.close()
        if ip and not ip.startswith("127."):
            return ip
    except Exception:
        pass
    return "127.0.0.1"

def do_launch_help(raw: str) -> str:
    """Підказати, як запустити проєкт.

    ``raw`` — або шлях до скрипта, або звичайна фраза («як запустити
    проєкт»). Раніше фраза сприймалась як шлях і падала з FileNotFoundError.
    """
    candidate = (raw or "").strip().strip('"\'')
    looks_like_path = bool(candidate) and (
        candidate.lower().endswith((".py", ".bat", ".cmd", ".ps1", ".js"))
        or "/" in candidate or "\\" in candidate
    )
    path = None
    if looks_like_path:
        try:
            path = _safe_path(candidate, must_exist=True)
        except (FileNotFoundError, ValueError, OSError):
            path = None
    if path is None:
        hints: list[str] = []
        for name in ("run_ide.bat", "run_server.bat", "run_tests.bat", "install.bat",
                     "main.py", "server.py", "app.py"):
            if (WORKSPACE / name).exists():
                hints.append(name)
        py = str(Path(sys.executable))
        lines = ["Не вказано файл. Ось що є в робочій теці:"]
        if not hints:
            lines.append("  (типових точок входу не знайдено — назви файл, наприклад app.py)")
        for name in hints:
            lines.append(f"  {name}" if name.endswith(".bat") else f"  {py} {name}")
        return "\n".join(lines)
    if path.is_dir():
        return "Вкажи файл скрипта, наприклад app.py."
    code = _read_text(path) if path.suffix.lower() == ".py" else ""
    py = str(Path(sys.executable))
    lines = ["Запуск на цьому Windows:", f"  {py} {path}"]
    if any(token in code.lower() for token in ("flask", "fastapi", "app.run(", "streamlit")):
        ports = re.findall(r"port\s*=\s*(\d+)", code)
        port = ports[-1] if ports else "5000"
        lines.append("Для веб-сервера став host='0.0.0.0'.")
        lines.append(f"З іншого пристрою в мережі: http://{ip_lan_locale()}:{port}")
        lines.append("127.0.0.1 з іншого комп'ютера — це не цей ПК.")
    return "\n".join(lines)

def parse_project_files(answer: str, default_name: str) -> list[tuple[str, str]]:
    """Один блок ```python або кілька секцій ### FILE: шлях."""
    segments = re.split(r"### FILE:\s*([^\n#]+)", answer)
    files: list[tuple[str, str]] = []
    if len(segments) > 1:
        for i in range(1, len(segments), 2):
            name = segments[i].strip(" #\r\n")
            raw = segments[i + 1] if i + 1 < len(segments) else ""
            blocks = re.findall(r"```(?:\w+)?\n(.*?)```", raw, re.DOTALL)
            code = "\n\n".join(blocks) if blocks else raw.strip()
            if name and code.strip():
                files.append((name, code.strip() + "\n"))
    if files:
        hinted = os.path.basename(default_name)
        if hinted not in {"app.py", "main.py"}:
            files = [
                (hinted if os.path.basename(name) in {"app.py", "main.py"} and name == os.path.basename(name) else name, code)
                for name, code in files
            ]
        return files
    blocks = re.findall(r"```(?:python)?\n(.*?)```", answer, re.DOTALL)
    code = (blocks[0] if blocks else answer).strip()
    return [(default_name, code + "\n")]


def do_build_project(file_hint: str, request: str) -> str:
    raw_path = file_hint or "app.py"
    path = _safe_path(raw_path, must_exist=False)
    if path.suffix.lower() != ".py":
        path = _safe_path("app.py", must_exist=False)
    client, model, label = scegli_motore("auto")
    context = ""
    if path.exists():
        context = "\nПоточний файл:\n" + _read_text(path)[:2500]
    prompt = (
        f"Головний файл: {path.name}. Прохання: {request}{context}\n"
        "Якщо вистачає одного файлу, поверни його в ```python.\n"
        "Якщо потрібні шаблони, css або ще файли, для КОЖНОГО файлу напиши рядок "
        "### FILE: відносний/шлях.ext ### і одразу код у ``` ... ```.\n"
        "Веб-сервер слухає host 0.0.0.0."
    )
    answer = ""
    for chunk in client.chat(
        model=model,
        messages=[
            {"role": "system", "content": "Ти збираєш робочий проєкт. Кілька файлів віддавай секціями ### FILE."},
            {"role": "user", "content": prompt},
        ],
        stream=True,
    ):
        answer += chunk["message"]["content"]
    written: list[str] = []
    diffs: list[str] = []
    main_path: Path | None = None
    for name, code in parse_project_files(answer, path.name):
        candidate = Path(name)
        target = _safe_path(str(candidate) if candidate.is_absolute() else str(path.parent / name), must_exist=False)
        summary = apply_text(target, code, _relative, edits_store(DB_PATH))
        written.append(_relative(target))
        diffs.append(f"--- {_relative(target)} ---\n{summary[:700]}")
        if target.name == path.name:
            main_path = target
        elif main_path is None and target.suffix.lower() == ".py":
            main_path = target
    if main_path is None:
        main_path = path
    repair = esegui_e_ripara_codice(client, model, label, str(main_path))
    return (
        f"Написано {len(written)} файл(ів) через {label}: {', '.join(written)}.\n"
        + "\n".join(diffs)
        + f"\n{do_launch_help(str(main_path))}\n{repair}"
    )

_SOCIAL_LIMITS = {"x": 280, "facebook": 1500, "telegram": 3500, "mastodon": 500}

def _social_platforms(text: str) -> list[str]:
    low = text.lower()
    found = []
    if any(word in low for word in ("facebook", "фейсбук")):
        found.append("facebook")
    if any(word in low for word in ("telegram", "телеграм")):
        found.append("telegram")
    if any(word in low for word in ("mastodon", "мастодон")):
        found.append("mastodon")
    if any(word in low for word in ("twitter", "твіт", " x")):
        found.append("x")
    return found

def _social_topic(text: str) -> str:
    match = re.search(r"(?:пост|допис)\s+(?:про|для|на тему)\s+(.+)", text, flags=re.I)
    if match:
        return match.group(1).strip()
    return text.strip()

def _draft_social(platform: str, topic: str) -> str:
    limit = _SOCIAL_LIMITS[platform]
    try:
        client, model, _label = scegli_motore("auto")
        answer = ""
        for chunk in client.chat(
            model=model,
            messages=[
                {"role": "system", "content": "Ти пишеш один пост для соцмережі. Лише текст поста, без пояснень."},
                {"role": "user", "content": (
                    f"Майданчик: {platform}. Ліміт: {limit} символів. Мова: українська.\n"
                    f"Тема: {topic}\n"
                    "Без обіцянок заробітку, без заклику щось терміново купити, без вигаданих фактів про людину."
                )},
            ],
            stream=True,
        ):
            answer += chunk["message"]["content"]
        answer = re.sub(r"```.*?```", "", answer, flags=re.S).strip()
        if answer:
            return answer[:limit]
    except Exception as exc:
        log.warning("чернетка поста: %s", exc)
    return topic[:limit]

def _save_social_draft(platform: str, text: str) -> str:
    folder = WORKSPACE / ".mcp_rag" / "social_drafts"
    folder.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    path = folder / f"{stamp}-{platform}.txt"
    path.write_text(text + "\n", encoding="utf-8")
    return _relative(path)

def _hide_secrets(text: str, secrets: list[str]) -> str:
    hidden = text
    for secret in secrets:
        if secret:
            hidden = hidden.replace(secret, "***")
    return hidden

def _post_json(url: str, payload: dict, headers: dict, secrets: list[str]) -> str:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", **headers},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            body = response.read(2000).decode("utf-8", errors="replace")
            return "опубліковано, відповідь сервісу: " + _hide_secrets(body[:300], secrets)
    except Exception as exc:
        note = _hide_secrets(f"{type(exc).__name__}: {exc}", secrets)[:240]
        return f"не опубліковано: {note}"

def _publish_social(platform: str, text: str) -> str:
    if platform == "x":
        token = os.environ.get("MCP_X_ACCESS_TOKEN", "").strip()
        if not token:
            return "X не опубліковано: додай MCP_X_ACCESS_TOKEN (OAuth токен користувача з правом писати пости)."
        return "X: " + _post_json(
            "https://api.twitter.com/2/tweets",
            {"text": text},
            {"Authorization": f"Bearer {token}"},
            [token],
        )
    if platform == "facebook":
        page = os.environ.get("MCP_FACEBOOK_PAGE_ID", "").strip()
        token = os.environ.get("MCP_FACEBOOK_PAGE_TOKEN", "").strip()
        if not page or not token:
            return "Facebook не опубліковано: потрібні MCP_FACEBOOK_PAGE_ID і MCP_FACEBOOK_PAGE_TOKEN."
        url = f"https://graph.facebook.com/v21.0/{urllib.parse.quote(page)}/feed"
        return "Facebook: " + _post_json(url, {"message": text, "access_token": token}, {}, [token])
    if platform == "telegram":
        token = os.environ.get("MCP_TELEGRAM_BOT_TOKEN", "").strip()
        chat = os.environ.get("MCP_TELEGRAM_CHAT_ID", "").strip()
        if not token or not chat:
            return "Telegram не опубліковано: потрібні MCP_TELEGRAM_BOT_TOKEN і MCP_TELEGRAM_CHAT_ID."
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        return "Telegram: " + _post_json(url, {"chat_id": chat, "text": text}, {}, [token])
    token = os.environ.get("MCP_MASTODON_TOKEN", "").strip()
    base = os.environ.get("MCP_MASTODON_BASE_URL", "").strip().rstrip("/")
    if not token or not base:
        return "Mastodon не опубліковано: потрібні MCP_MASTODON_BASE_URL і MCP_MASTODON_TOKEN."
    return "Mastodon: " + _post_json(
        base + "/api/v1/statuses",
        {"status": text, "visibility": "public"},
        {"Authorization": f"Bearer {token}"},
        [token],
    )

def do_preview_local(raw: str) -> str:
    raw = (raw or "").strip()
    match = re.search(r"https?://\S+", raw)
    if match:
        url = match.group(0).rstrip(".,)")
        host = (urllib.parse.urlparse(url).hostname or "").lower()
        if host not in {"127.0.0.1", "localhost"}:
            return "Дивлюсь лише сторінки на цьому ПК: http://127.0.0.1 або http://localhost."
    else:
        file_match = re.search(r"[\w./\\-]+\.html?", raw, flags=re.I)
        if not file_match:
            return "Дай адресу localhost або шлях до html у проєкті."
        page_path = _safe_path(file_match.group(0), must_exist=True)
        url = page_path.as_uri()
    if not _HAS_PLAYWRIGHT:
        return "Playwright не встановлено, локальну сторінку не відкрив."
    errors: list[str] = []
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page()
            page.on("pageerror", lambda exc: errors.append(str(exc)))
            page.goto(url, timeout=20000, wait_until="domcontentloaded")
            title = page.title()
            body = " ".join(page.inner_text("body").split())[:1500]
            browser.close()
    except Exception as exc:
        return f"Сторінку не відкрив: {type(exc).__name__}: {exc}"
    problem = ("\nПомилки сторінки:\n" + "\n".join(errors[:8])) if errors else ""
    return f"{url}\nЗаголовок: {title}\n{body}{problem}"


def do_social_post(phrase: str) -> str:
    phrase = (phrase or "").strip()
    if not phrase:
        return "Напиши тему поста."
    named = _social_platforms(phrase)
    publish = any(word in phrase.lower() for word in ("опублікуй", "виклади", "запости", "publish"))
    targets = named or ["x", "facebook"]
    topic = _social_topic(phrase)
    blocks = []
    for platform in targets:
        text = _draft_social(platform, topic)
        saved = _save_social_draft(platform, text)
        blocks.append(f"{platform} ({len(text)} симв.), чернетка {saved}:\n{text}")
        if publish and named:
            blocks.append(_publish_social(platform, text))
    if publish and not named:
        blocks.append("Мережу не названо, тому в стрічку нічого не пішло. Скажи, наприклад: опублікуй пост у телеграм.")
    elif not publish:
        blocks.append("Це чернетка. Щоб викласти, скажи «опублікуй» і назви мережу: x, facebook, telegram або mastodon.")
    return "\n\n".join(blocks)

AGENT_INSTRUCTIONS = """
Завжди відповідай користувачу українською, навіть якщо результат інструмента англійською.
Спочатку виклич master_agent_router: intent=auto, request=дослівні слова користувача.
Не пиши план англійською і не питай дозволу дивитися проєкт. Не вигадуй інструменти.
""".strip()

mcp = MCPServer(
    "blackchpok-ai",
    title="BlackChpok AI",
    description="Єдиний інструмент master_agent_router для файлів, термінала, git і пошуку.",
    instructions=AGENT_INSTRUCTIONS,
    version="10.0.0",
)

IntentName = Literal[
    "auto",
    "talk",
    "build_project",
    "launch_help",
    "memory_search",
    "refresh_memory",
    "night_shift",
    "chat_history",
    "set_engine",
    "install_package",
    "project_context",
    "ask_browser_ai",
    "system_info",
    "list_intents",
    "list_dir",
    "glob_files",
    "grep",
    "find_symbol",
    "project_outline",
    "project_map",
    "analyze_project",
    "remember_project",
    "db_schema",
    "preview_local",
    "index_symbols",
    "read_file",
    "read_files",
    "write_file",
    "append_file",
    "replace_in_file",
    "replace_all",
    "replace_lines",
    "delete_file",
    "move_file",
    "copy_file",
    "mkdir",
    "file_info",
    "hash_file",
    "diff_files",
    "diagnostics",
    "review_code",
    "run_shell",
    "run_tests",
    "git_context",
    "git_diff",
    "git_log",
    "git_show",
    "search_web",
    "social_post",
    "finance_brief",
    "fetch_url",
    "rag_search",
    "save_rule",
    "list_rules",
    "todo_write",
    "todo_list",
    "clear_cache",
    "env_which",
    "index_project",
    "run_and_repair",
    "undo_edit",
    "self_test",
]

_TOOLS = AgentTools(WORKSPACE, _safe_path, _read_text, _walk_files, _relative, _rag, DB_PATH)
_ROUTES = _TOOLS.routes()

@mcp.tool(
    description=(
        "Викликай цей інструмент до будь-якого тексту. intent=auto, request=дослівні слова користувача. "
        "Після результату відповідай лише українською. Не вигадуй інструменти."
    )
)
def master_agent_router(
    intent: str = "auto",
    query: str = "",
    file_path: str = "",
    extra: str = "",
    request: str = "",
) -> str:
    """Приймає звичайну мову і виконує відповідну дію.

    ``intent`` навмисно звичайний рядок, а не ``Literal``: інакше невідоме
    значення падало ще до виконання з сирою помилкою валідації pydantic,
    і модель не бачила підказки, які intent'и існують.
    """
    origin = (intent or "auto").strip().lower()
    phrase = (request or query or "").strip()
    key, used_query, used_path, used_extra = origin, query, file_path, extra
    if origin == "auto":
        decision = classify(phrase)
        key = decision.intent
        used_query = query or decision.query
        used_path = file_path or decision.file_path
        used_extra = extra or decision.extra
    label = LABELS.get(key, key)
    try:
        result = _execute(key, used_query, used_path, used_extra, phrase)
    except Exception as exc:
        result = f"Помилка виконання {key}: {type(exc).__name__}: {exc}"
    if origin == "auto" and phrase:
        _log_hit(phrase, key, used_path)
        _remember(phrase, result)
        # Службову інструкцію ставимо ПЕРЕД результатом, а не в кінці:
        # коли вона стоїть останньою, малі моделі повторюють її замість
        # відповіді користувачу (перевірено на Qwen2.5-Coder 14B).
        head = f"Зрозумів як: {label}."
        return _ukrainian(_fit(
            f"{head}\n\n{result}\n\n"
            f"Правило: відповідай користувачу українською за цим результатом. "
            f"Викликай master_agent_router повторно лише якщо задача справді не закрита."
            f"\n{_memory_footer()}"
        ))
    return _ukrainian(result)

def _ukrainian(text: str) -> str:
    return text or ""


def _execute(key: str, query: str, file_path: str, extra: str, phrase: str) -> str:
    # --- Віртуальні інструменти, реалізовані в server.py ---
    if key == "talk":
        return do_talk(phrase or query)
    if key == "ask_browser_ai":
        return do_ask_browser_ai(query or phrase, (extra or "gemini").strip().lower())
    if key == "run_and_repair":
        client, model, hardware = scegli_motore("auto")
        return esegui_e_ripara_codice(client, model, hardware, file_path or query)
    if key == "build_project":
        return do_build_project(file_path, phrase or query)
    if key == "social_post":
        return do_social_post(phrase or query)
    if key == "launch_help":
        return do_launch_help(file_path or query)
    if key == "memory_search":
        return do_memory_search(phrase or query)
    if key == "chat_history":
        return do_chat_history(phrase or query)
    if key == "set_engine":
        return do_set_engine(query or extra or phrase)
    if key == "install_package":
        planned = shell_plan(phrase or query)
        if planned:
            return do_cli(phrase or query, planned, "180")
        return do_install_package(query or extra)
    if key == "run_shell":
        return do_cli(phrase, query, extra or "180")
    if key == "project_context":
        return do_project_context(file_path or query or ".")

    # --- Явна обробка інструментів, які є тільки в server.py ---
    if key == "preview_local":
        return do_preview_local(phrase or query or file_path)
    if key == "index_project":
        return do_index_project(file_path or query or ".", phrase)
    if key == "self_test":
        return router_self_test(_TOOLS, master_agent_router)

    if key == "undo_edit":
        return _TOOLS.undo_edit(file_path or query)

    # --- Реальні інструменти з AgentTools.routes() ---
    route = _ROUTES.get(key)
    if route is None:
        return f"Невідомий intent '{key}'. Доступні:\n{_TOOLS.list_intents()}"

    routed_query = query
    if key in {"grep", "find_symbol", "search_web", "finance_brief", "save_rule", "run_shell", "todo_write"} and phrase and not query:
        routed_query = phrase
    return route(routed_query, file_path, extra)


if __name__ == "__main__":
    log.info("Запуск Semantic Router v9.1, vibe+loop")
    mcp.run()