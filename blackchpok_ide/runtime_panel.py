"""Панель AI RUNTIME: моделі, завантаження, GPU, контекст, бенчмарк.

Призначення — дати повний контроль над ВЛАСНИМ рушієм, і показувати
тільки те, що справді виміряно:

* список моделей із метаданими GGUF (architecture, quantization, шари,
  контекст) і прогнозом RAM/VRAM;
* завантаження/вивантаження моделі, вибір контексту й кількості шарів на
  GPU (з підказкою, скільки реально влізе);
* живі показники: VRAM через ``nvidia-smi``, RAM процесу, KV-кеш,
  швидкість генерації;
* бенчмарк із справжніми числами (tok/s, TTFT, p50/p95);
* журнал запитів рушія з тривалістю й помилками.

Панель не блокує Tk: усе важке — у фонових потоках, результати — через
``queue`` + ``after``. Жодна кнопка не існує «для краси»: кожна викликає
метод :class:`~blackchpok_ide.native.api.NativeRuntime`.
"""

from __future__ import annotations

import queue
import threading
import tkinter as tk
from typing import Any, Callable, Optional

from . import theme, widgets

#: Як часто оновлювати живі показники (мілісекунди).
LIVE_INTERVAL = 3000


class RuntimePanel(tk.Frame):
    """Керування вбудованим рушієм BLACKCHPOK."""

    def __init__(
        self,
        master: tk.Misc,
        fonts: theme.Theme,
        runtime_provider: Callable[[], Any],
        *,
        on_model_activated: Optional[Callable[[str], None]] = None,
        on_status: Optional[Callable[[str], None]] = None,
    ) -> None:
        super().__init__(master, bg=theme.BG_ALT, bd=0, highlightthickness=0)
        self.fonts = fonts
        self._runtime_provider = runtime_provider
        self.on_model_activated = on_model_activated
        self.on_status = on_status
        self._queue: "queue.Queue[tuple[str, object]]" = queue.Queue()
        self._after: Optional[str] = None
        self._live_after: Optional[str] = None
        self._busy = False
        self._selected = ""
        self._models: list[dict[str, Any]] = []
        #: Живі показники збираються з трьох незалежних джерел (статус
        #: рушія, nvidia-smi, RAM); тримаємо їх окремо, щоб оновлення
        #: одного не стирало решту.
        self._metrics_text = ""
        self._gpu_text = ""
        self._memory_text = ""
        self._build()
        self.bind("<Destroy>", self._on_destroy, add="+")
        self.refresh_models()
        self.refresh_status()
        self._schedule_live()

    # ── життєвий цикл ──────────────────────────────────────────────────────
    def _on_destroy(self, event=None) -> None:
        if event is not None and getattr(event, "widget", self) is not self:
            return
        for name in ("_after", "_live_after"):
            handle = getattr(self, name, None)
            if handle is not None:
                try:
                    self.after_cancel(handle)
                except tk.TclError:
                    pass
                setattr(self, name, None)

    @property
    def runtime(self):
        return self._runtime_provider()

    def _say(self, text: str) -> None:
        if self.on_status is not None:
            self.on_status(text)

    # ── побудова ───────────────────────────────────────────────────────────
    def _build(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(3, weight=1)

        head = tk.Frame(self, bg=theme.BG_ALT)
        head.grid(row=0, column=0, sticky="ew", padx=theme.SPACE_MD,
                  pady=(theme.SPACE_MD, 2))
        head.columnconfigure(0, weight=1)
        tk.Label(head, text="AI RUNTIME · ВЛАСНИЙ РУШІЙ", bg=theme.BG_ALT,
                 fg=theme.FG_DIM, font=self.fonts.ui_tiny, anchor="w").grid(
            row=0, column=0, sticky="w")
        self.lib_label = tk.Label(head, text="перевіряю рушій…", bg=theme.BG_ALT,
                                  fg=theme.FG_FAINT, font=("Segoe UI", 8),
                                  anchor="w", justify="left", wraplength=265)
        self.lib_label.grid(row=1, column=0, sticky="ew", pady=(2, 0))
        widgets.IconButton(head, "⟳", self.refresh_all, bg=theme.BG_ALT,
                           fg=theme.FG_FAINT, font=("Segoe UI", 10),
                           tooltip="Оновити все").grid(row=0, column=1, rowspan=2)

        self.metrics = tk.Label(self, text="", bg=theme.BG_ALT, fg=theme.FG,
                                font=("Segoe UI", 8), anchor="w", justify="left",
                                wraplength=270)
        self.metrics.grid(row=1, column=0, sticky="ew", padx=theme.SPACE_MD,
                          pady=(4, 2))

        actions = tk.Frame(self, bg=theme.BG_ALT)
        actions.grid(row=2, column=0, sticky="ew", padx=theme.SPACE_MD, pady=(2, 2))
        self.ctx_var = tk.StringVar(value="")
        ctx_wrap = tk.Frame(actions, bg=theme.BG_ALT)
        ctx_wrap.grid(row=0, column=0, columnspan=4, sticky="ew", pady=(0, 3))
        tk.Label(ctx_wrap, text="контекст:", bg=theme.BG_ALT, fg=theme.FG_FAINT,
                 font=("Segoe UI", 8)).pack(side="left")
        self.ctx_entry = tk.Entry(ctx_wrap, textvariable=self.ctx_var, width=8,
                                  bg=theme.BG_INPUT, fg=theme.FG, relief="flat",
                                  insertbackground=theme.FG, font=("Segoe UI", 8),
                                  bd=0)
        self.ctx_entry.pack(side="left", padx=(4, 6), ipady=2)
        tk.Label(ctx_wrap, text="шарів на GPU:", bg=theme.BG_ALT, fg=theme.FG_FAINT,
                 font=("Segoe UI", 8)).pack(side="left")
        self.layers_var = tk.StringVar(value="")
        tk.Entry(ctx_wrap, textvariable=self.layers_var, width=6, bg=theme.BG_INPUT,
                 fg=theme.FG, relief="flat", insertbackground=theme.FG,
                 font=("Segoe UI", 8), bd=0).pack(side="left", padx=(4, 0), ipady=2)

        buttons = (
            ("Завантажити", self.run_load, "Завантажити вибрану модель у рушій"),
            ("Вивантажити", self.run_unload, "Звільнити RAM/VRAM"),
            ("Бенчмарк", self.run_benchmark, "Заміряти tok/s і TTFT на реальній генерації"),
            ("Перевірити", self.run_inspect, "Прочитати GGUF і перевірити цілісність"),
        )
        for column, (label, command, tip) in enumerate(buttons):
            chip = widgets.Chip(actions, label, command=command)
            chip.grid(row=1, column=column, padx=(0, 4), pady=2, sticky="w")
            widgets.Tip(chip, tip)

        self.scroll = widgets.ScrollFrame(self, bg=theme.BG_ALT)
        self.scroll.grid(row=3, column=0, sticky="nsew", padx=theme.SPACE_MD,
                         pady=(4, theme.SPACE_SM))
        self.list_host = self.scroll.inner

        self.log_label = tk.Label(self, text="", bg=theme.BG_ALT, fg=theme.FG_FAINT,
                                  font=("Consolas", 7), anchor="w", justify="left",
                                  wraplength=270)
        self.log_label.grid(row=4, column=0, sticky="ew", padx=theme.SPACE_MD,
                            pady=(0, theme.SPACE_SM))

    # ── оновлення ──────────────────────────────────────────────────────────
    def refresh_all(self) -> None:
        self.refresh_models()
        self.refresh_status()

    def refresh_models(self) -> None:
        runtime = self.runtime
        if runtime is None or self._busy:
            return
        self._busy = True

        def work() -> None:
            try:
                self._queue.put(("models", runtime.list_models()))
            except Exception as exc:                 # noqa: BLE001
                self._queue.put(("error", f"Список моделей: {exc}"))
            finally:
                self._busy = False

        threading.Thread(target=work, daemon=True, name="runtime-models").start()
        self._schedule_pump()

    def refresh_status(self) -> None:
        runtime = self.runtime
        if runtime is None:
            return

        def work() -> None:
            try:
                self._queue.put(("status", runtime.get_runtime_status()))
                self._queue.put(("gpu", runtime.get_gpu_status()))
                self._queue.put(("memory", runtime.get_memory_status()))
            except Exception as exc:                 # noqa: BLE001
                self._queue.put(("error", f"Статус рушія: {exc}"))

        threading.Thread(target=work, daemon=True, name="runtime-status").start()
        self._schedule_pump()

    def _schedule_live(self) -> None:
        if self._live_after is None and self.winfo_exists():
            self._live_after = self.after(LIVE_INTERVAL, self._live_tick)

    def _live_tick(self) -> None:
        self._live_after = None
        self.refresh_status()
        self._schedule_live()

    def _schedule_pump(self) -> None:
        if self._after is None:
            self._after = self.after(80, self._pump)

    def _pump(self) -> None:
        self._after = None
        try:
            while True:
                kind, payload = self._queue.get_nowait()
                if kind == "models":
                    self._apply_models(payload)          # type: ignore[arg-type]
                elif kind == "status":
                    self._apply_status(payload)          # type: ignore[arg-type]
                elif kind == "gpu":
                    self._apply_gpu(payload)             # type: ignore[arg-type]
                elif kind == "memory":
                    self._apply_memory(payload)          # type: ignore[arg-type]
                elif kind == "bench":
                    self._apply_bench(payload)           # type: ignore[arg-type]
                elif kind == "info":
                    self._apply_inspect(payload)         # type: ignore[arg-type]
                elif kind == "message":
                    self._say(str(payload))
                    self.log_label.configure(text=str(payload)[:500])
                elif kind == "error":
                    self._say(f"✗ {payload}")
                    self.log_label.configure(text=f"✗ {payload}"[:500])
                elif kind == "reload":
                    self.refresh_all()
        except queue.Empty:
            pass
        if self.winfo_exists():
            self._after = self.after(120, self._pump)

    # ── відображення ───────────────────────────────────────────────────────
    def _apply_models(self, summary: dict[str, Any]) -> None:
        self._models = (summary or {}).get("models") or []
        loaded = (summary or {}).get("loaded") or ""
        self.lib_label.configure(
            text=f"тека: {summary.get('folder', '')}\n"
                 f"моделей: {summary.get('count', 0)} · "
                 f"{summary.get('total_gb', 0)} ГБ · "
                 f"вільно {summary.get('free_gb', 0)} ГБ"
                 + (f"\nзавантажено: {loaded.split(chr(92))[-1]}" if loaded else "")
        )
        for child in self.list_host.winfo_children():
            child.destroy()
        if not self._models:
            tk.Label(self.list_host, text="Моделей .gguf не знайдено.",
                     bg=theme.BG_ALT, fg=theme.FG_FAINT, font=("Segoe UI", 8),
                     anchor="w").pack(fill="x", padx=theme.SPACE_SM,
                                      pady=theme.SPACE_SM)
            return
        for model in self._models:
            self._model_card(model, loaded=model.get("path") == loaded)

    def _model_card(self, model: dict[str, Any], *, loaded: bool) -> None:
        path = str(model.get("path") or "")
        bg = theme.BG_ACTIVE if loaded else theme.BG_CARD
        card = tk.Frame(self.list_host, bg=bg, bd=0, highlightthickness=0)
        card.pack(fill="x", pady=2, padx=1)
        name = str(model.get("name") or model.get("key") or "")
        mark = "● " if loaded else ""
        title = tk.Label(card, text=f"{mark}{name}", bg=bg, fg=theme.FG_BRIGHT,
                         font=("Segoe UI", 8, "bold"), anchor="w",
                         wraplength=250, justify="left")
        title.pack(fill="x", padx=theme.SPACE_SM, pady=(3, 0))
        bits = [
            str(model.get("quant") or ""),
            f"{model.get('parameters_b', 0)}B" if model.get("parameters_b") else "",
            f"ctx {int(model.get('context') or 0) // 1024}K" if model.get("context") else "",
            f"{model.get('size_gb', 0)} ГБ",
            {"gpu": "GPU", "hybrid": "гібрид", "cpu": "CPU",
             "impossible": "не влізе"}.get(str(model.get("fits")), ""),
        ]
        meta = tk.Label(card, text=" · ".join(part for part in bits if part),
                        bg=bg, fg=theme.FG_DIM, font=("Segoe UI", 7), anchor="w")
        meta.pack(fill="x", padx=theme.SPACE_SM)
        forecast = (f"~{model.get('vram_needed_gb', 0)} ГБ VRAM · "
                    f"{model.get('suggested_gpu_layers', 0)} шарів · "
                    f"~{model.get('ram_needed_gb', 0)} ГБ RAM")
        tk.Label(card, text=forecast, bg=bg, fg=theme.FG_FAINT,
                 font=("Segoe UI", 7), anchor="w").pack(
            fill="x", padx=theme.SPACE_SM, pady=(0, 3))
        for widget in (card, title, meta):
            widget.bind("<Button-1>", lambda _e, p=path: self._select(p))
            try:
                widget.configure(cursor="hand2")
            except tk.TclError:
                pass

    def _select(self, path: str) -> None:
        self._selected = path
        for model in self._models:
            if str(model.get("path")) == path:
                suggested = int(model.get("suggested_ctx") or 4096)
                layers = int(model.get("suggested_gpu_layers") or 0)
                self.ctx_var.set(str(suggested))
                self.layers_var.set(str(layers))
                self._say(f"Вибрано {model.get('name')} · ctx {suggested} · "
                          f"шарів на GPU {layers}")
                return

    def _apply_status(self, status: dict[str, Any]) -> None:
        library = (status or {}).get("library") or {}
        if not library.get("ok"):
            self.lib_label.configure(
                text=f"рушій недоступний: {library.get('error', 'немає llama.dll')}")
            return
        devices = library.get("devices") or []
        device_text = ", ".join(
            f"{item.get('name')} ({item.get('memory_total_mb', 0):.0f} МБ)"
            for item in devices if item.get("kind") != "cpu") or "без GPU"
        self.lib_label.configure(
            text=f"llama.cpp {library.get('version', '')} · {device_text}")
        self._apply_metrics(status)

    def _apply_metrics(self, status: dict[str, Any]) -> None:
        parts: list[str] = []
        if status.get("loaded"):
            parts.append(f"модель: {status.get('description', '')}")
            parts.append(f"ctx {status.get('context_actual', 0)} · "
                         f"шари GPU {status.get('gpu_layers', 0)} · "
                         f"KV {status.get('cache_type', '')}")
            kv = status.get("kv") or {}
            used = kv.get("cached_tokens", 0)
            capacity = kv.get("capacity", 0) or 1
            parts.append(f"KV: {used}/{capacity} токенів · "
                         f"переиспользовано {kv.get('saved_tokens', 0)}")
            parts.append(f"завантаження {status.get('load_ms', 0)} мс")
        requests = status.get("requests") or []
        if requests:
            last = requests[-1]
            mark = "✓" if last.get("ok") else "✗"
            parts.append(f"{mark} {last.get('operation')} "
                         f"{last.get('duration_ms')} мс"
                         + (f" · {last.get('error')}" if last.get("error") else ""))
        self._metrics_text = "\n".join(parts) or "модель не завантажена"
        self._render_metrics()

    def _apply_gpu(self, payload: dict[str, Any]) -> None:
        gpus = payload.get("nvidia") or []
        if not gpus:
            self._gpu_text = "GPU: nvidia-smi недоступний"
            return
        gpu = gpus[0]
        self._gpu_text = (f"GPU: {gpu.get('name')} · "
                          f"{gpu.get('vram_used_mb', 0):.0f}/"
                          f"{gpu.get('vram_total_mb', 0):.0f} МБ · "
                          f"завантаження {gpu.get('utilization_percent', 0):.0f}% · "
                          f"{gpu.get('temperature_c', 0):.0f}°C")
        self._render_metrics()

    def _apply_memory(self, payload: dict[str, Any]) -> None:
        self._memory_text = (
            f"RAM: система {payload.get('system_available_gb', 0):.1f}/"
            f"{payload.get('system_total_gb', 0):.1f} ГБ вільно · "
            f"процес {payload.get('process_rss_mb', 0):.0f} МБ")
        self._render_metrics()

    def _render_metrics(self) -> None:
        pieces = [getattr(self, "_metrics_text", ""),
                  getattr(self, "_gpu_text", ""),
                  getattr(self, "_memory_text", "")]
        text = "\n".join(part for part in pieces if part)
        if text:
            self.metrics.configure(text=text)

    def _apply_bench(self, payload: dict[str, Any]) -> None:
        runs = payload.get("runs") or []
        lines = [
            f"Бенчмарк: {payload.get('tokens_per_second', 0)} tok/s "
            f"(p95 {payload.get('tokens_per_second_p95', 0)}), "
            f"TTFT {payload.get('time_to_first_token_ms', 0)} мс "
            f"(p95 {payload.get('time_to_first_token_ms_p95', 0)})",
            f"контекст {payload.get('context', 0)} · шарів на GPU "
            f"{payload.get('gpu_layers', 0)} · прогонів {len(runs)}",
        ]
        gpu = (payload.get("gpu") or [{}])[0]
        if gpu:
            lines.append(f"VRAM: {gpu.get('vram_used_mb', 0):.0f} МБ · "
                         f"завантаження {gpu.get('utilization_percent', 0):.0f}%")
        self.log_label.configure(text="\n".join(lines)[:600])
        self._say(lines[0])

    def _apply_inspect(self, payload: dict[str, Any]) -> None:
        integrity = payload.get("integrity") or {}
        notes = payload.get("notes") or []
        lines = [
            f"{payload.get('display_name', '')} · {payload.get('architecture', '')} · "
            f"{payload.get('quant', '')}",
            f"шарів {payload.get('layer_count', 0)} · ctx тренування "
            f"{payload.get('context_train', 0)} · словник {payload.get('vocab_size', 0)}",
            f"шаблон чату: {'є' if payload.get('has_chat_template') else 'немає'} · "
            f"tool calling: {'так' if payload.get('has_chat_template') else 'адаптер'}",
            f"цілісність: {'гаразд' if integrity.get('ok') else 'ПРОБЛЕМИ'}",
        ]
        for note in notes[:3]:
            lines.append(f"· {note}")
        self.log_label.configure(text="\n".join(lines)[:800])
        self._say(lines[0])

    # ── дії ────────────────────────────────────────────────────────────────
    def run_load(self) -> None:
        runtime = self.runtime
        if runtime is None or not self._selected:
            self._say("Спершу вибери модель у списку.")
            return
        try:
            ctx = int(self.ctx_var.get() or 0)
        except ValueError:
            ctx = 0
        try:
            layers = int(self.layers_var.get())
        except ValueError:
            layers = None
        self._say(f"Завантажую модель (ctx {ctx or 'авто'})…")

        def work() -> None:
            try:
                info = runtime.load_model(
                    self._selected, ctx=ctx, gpu_layers=layers,
                    on_progress=lambda text: self._queue.put(("message", text)))
                self._queue.put(("message",
                                 f"Модель завантажена: {info.get('description')} "
                                 f"(ctx {info.get('context_actual')}, "
                                 f"GPU-шарів {info.get('gpu_layers')})"))
                if self.on_model_activated is not None:
                    self.on_model_activated(info.get("path") or self._selected)
                self._queue.put(("reload", None))
            except Exception as exc:                 # noqa: BLE001
                self._queue.put(("error", str(exc)))

        threading.Thread(target=work, daemon=True, name="runtime-load").start()
        self._schedule_pump()

    def run_unload(self) -> None:
        runtime = self.runtime
        if runtime is None:
            return
        self._say("Вивантажую модель…")

        def work() -> None:
            try:
                data = runtime.unload_model()
                self._queue.put(("message",
                                 "Модель вивантажено." if data.get("unloaded")
                                 else "Моделі в пам'яті не було."))
                self._queue.put(("reload", None))
            except Exception as exc:                 # noqa: BLE001
                self._queue.put(("error", str(exc)))

        threading.Thread(target=work, daemon=True, name="runtime-unload").start()
        self._schedule_pump()

    def run_benchmark(self) -> None:
        runtime = self.runtime
        if runtime is None:
            return
        self._say("Заміряю швидкість на реальній генерації…")

        def work() -> None:
            try:
                self._queue.put(("bench", runtime.benchmark_model(runs=2,
                                                                 max_tokens=64)))
            except Exception as exc:                 # noqa: BLE001
                self._queue.put(("error", str(exc)))

        threading.Thread(target=work, daemon=True, name="runtime-bench").start()
        self._schedule_pump()

    def run_inspect(self) -> None:
        runtime = self.runtime
        target = self._selected or ""
        if runtime is None or not target:
            self._say("Спершу вибери модель.")
            return
        self._say("Читаю метадані GGUF…")

        def work() -> None:
            try:
                self._queue.put(("info", runtime.inspect_model(target)))
            except Exception as exc:                 # noqa: BLE001
                self._queue.put(("error", str(exc)))

        threading.Thread(target=work, daemon=True, name="runtime-inspect").start()
        self._schedule_pump()


__all__ = ["LIVE_INTERVAL", "RuntimePanel"]
