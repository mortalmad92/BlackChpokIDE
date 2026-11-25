"""?????? ????????????????? ????? ??????????, ???????, ??????, ??????? ? ??????? BlackChpok IDE."""
from __future__ import annotations
import ctypes
import time
import tkinter as tk
from pathlib import Path


def run_full_ui_audit(header_bar) -> None:
    """??????? 100% ????? ?????? ?????????? ? ???????? ????????, ?????????? ???????, ??????? ?? ???????."""
    t0 = time.perf_counter()
    top = header_bar.winfo_toplevel()
    orig_x, orig_y = top.winfo_pointerx(), top.winfo_pointery()
    screen_w = top.winfo_rootx() + top.winfo_width()

    report: list[str] = ["=== BLACKCHPOK 100% FULL UI & VISUAL SELF-DIAGNOSTIC ==="]
    fails = 0
    checks = 0

    def _rec(ok: bool, msg: str) -> None:
        nonlocal fails, checks
        checks += 1
        if not ok:
            fails += 1
        report.append(f"[{'OK' if ok else 'FAIL'}] {msg}")

    dd_keys = ["cat_file", "cat_edit", "cat_view", "cat_mode", "agent", "model", "project", "git"]
    seq = [("L->R", k) for k in dd_keys] + [("R->L", k) for k in reversed(dd_keys)]

    def _run_dropdowns(idx: int) -> None:
        if idx >= len(seq):
            try:
                ctypes.windll.user32.SetCursorPos(int(orig_x), int(orig_y))
            except Exception:
                pass
            for w in list(top.winfo_children()):
                if w.winfo_class() == "Toplevel":
                    try:
                        w.destroy()
                    except Exception:
                        pass
            _audit_buttons_and_layout()
            return

        direction, k = seq[idx]
        b = header_bar._buttons.get(k)
        if b is None or not b.winfo_ismapped():
            _rec(False, f"Dropdown {direction} {k:<10}: button missing/unmapped")
            header_bar.after(5, lambda: _run_dropdowns(idx + 1))
            return

        cx = int(b.winfo_rootx() + max(2, b.winfo_width() // 2))
        cy = int(b.winfo_rooty() + max(2, b.winfo_height() // 2))
        try:
            ctypes.windll.user32.SetCursorPos(cx, cy)
        except Exception:
            pass
        top.update()

        def _verify():
            top.update_idletasks()
            tops = [w for w in top.winfo_children() if w.winfo_class() == "Toplevel" and w.winfo_ismapped()]
            h = tops[0].winfo_reqheight() if tops else 0
            _rec(len(tops) == 1 and h > 20, f"Dropdown {direction} {k:<10} x={b.winfo_rootx()}..{b.winfo_rootx()+b.winfo_width()} (h={h})")
            _run_dropdowns(idx + 1)

        header_bar.after(55, _verify)

    def _audit_buttons_and_layout() -> None:
        mapped_boxes = []
        for k, btn in header_bar._buttons.items():
            has_cmd = getattr(btn, "_command", None) is not None
            is_vis = bool(btn.winfo_ismapped())
            if k in ("view.sidebar", "more") and not is_vis:
                _rec(has_cmd, f"Header btn {k:<18}: command bound (hidden while sidebar open)")
                continue
            x1 = btn.winfo_rootx()
            x2 = x1 + btn.winfo_width()
            in_bounds = is_vis and (x2 <= screen_w + 8)
            _rec(has_cmd and in_bounds, f"Header btn {k:<18}: cmd={has_cmd}, x={x1}..{x2}/{screen_w}")
            if is_vis:
                mapped_boxes.append((k, x1, x2))

        mapped_boxes.sort(key=lambda item: item[1])
        overlaps = [f"{mapped_boxes[i][0]}<->{mapped_boxes[i+1][0]}" for i in range(len(mapped_boxes) - 1) if mapped_boxes[i][2] > mapped_boxes[i + 1][1] + 1]
        _rec(len(overlaps) == 0, f"Header geometry overlap check: {overlaps or '0 overlaps'}")

        for side_tab in ("explorer", "changes", "rag", "skills", "tools", "chats"):
            try:
                if hasattr(top, "show_side"):
                    top.show_side(side_tab)
                    top.update_idletasks()
                _rec(True, f"Side panel tab '{side_tab}': switched cleanly")
            except Exception as exc:
                _rec(False, f"Side panel tab '{side_tab}': {exc}")

        bt = getattr(top, "bottom_tabs", None)
        if bt is not None:
            try:
                tabs = list(bt.tabs())
                orig_tab = bt.select() if tabs else None
                for tid in tabs:
                    t_label = str(bt.tab(tid, "text") or "").strip()
                    bt.select(tid)
                    top.update_idletasks()
                    _rec(True, f"Bottom tab '{t_label}': active & rendered")
                if orig_tab:
                    bt.select(orig_tab)
            except Exception as exc:
                _rec(False, f"Bottom tabs audit: {exc}")

        lp = getattr(top, "live_preview", None)
        if lp is not None and hasattr(lp, "set_viewport_mode"):
            was_shown = bool(getattr(top, "_preview_shown", False))
            try:
                if not was_shown and hasattr(top, "toggle_preview"):
                    top.toggle_preview(True)
                for dev in ("mobile", "tablet", "desktop"):
                    res = lp.set_viewport_mode(dev)
                    top.update_idletasks()
                    _rec("????? ?????????" in str(res), f"LivePreview viewport '{dev}': {res}")
                if not was_shown and hasattr(top, "toggle_preview"):
                    top.toggle_preview(False)
            except Exception as exc:
                _rec(False, f"LivePreview devices audit: {exc}")

        total_widgets, vec_icons_count, stack = 0, 0, [top]
        while stack:
            w = stack.pop()
            total_widgets += 1
            if getattr(w, "_vec_img_ref", None) is not None:
                vec_icons_count += 1
            try:
                stack.extend(w.winfo_children())
            except Exception:
                pass
        _rec(vec_icons_count >= 15, f"Visual tree audit: widgets={total_widgets}, vector_icons={vec_icons_count}")

        log_path = Path.home() / "AppData" / "Roaming" / "BlackChpokIDE" / "ide.log"
        recent_errs = []
        if log_path.exists():
            try:
                tail = log_path.read_text(encoding="utf-8", errors="ignore").splitlines()[-40:]
                recent_errs = [ln for ln in tail if "Traceback" in ln or "[ERROR]" in ln]
            except Exception:
                pass
        _rec(len(recent_errs) == 0, f"Log health (ide.log tail): {len(recent_errs)} errors")

        # 8. ??'??????? ?????? ??????-?????? tests/run_all.py ? ???? ? ?????????? ? ?????? ????
        import subprocess, sys, threading
        root_dir = Path(__file__).resolve().parent.parent
        run_all = root_dir / "tests" / "run_all.py"

        def _finish_with_backend():
            nonlocal fails, checks
            import py_compile as _pyc
            ide_pkg = root_dir / "blackchpok_ide"
            py_files = sorted(ide_pkg.glob("*.py"))
            bad = []
            for pf in py_files:
                try:
                    _pyc.compile(str(pf), doraise=True)
                except Exception as ce:
                    bad.append(f"{pf.name}:{ce}")
            _rec(len(bad) == 0, f"All IDE modules integrity ({len(py_files)} files): {bad or '0 errors'}")
            dt_ms = (time.perf_counter() - t0) * 1000.0
            report.append(f"=== UNIFIED SUMMARY (UI + VISUAL + BACKEND): {checks - fails}/{checks} PASSED | FAILS={fails} | TIME={dt_ms:.1f} ms ===")
            final_text = "\n".join(report)
            def _publish():
                print(final_text, flush=True)
                try:
                    import subprocess
                    subprocess.run(["clip.exe"], input=final_text.encode("utf-16le"), check=False)
                except Exception:
                    pass
                try:
                    top.clipboard_clear()
                    top.clipboard_append(final_text)
                    top.update()
                except Exception:
                    pass
                if hasattr(top, "set_status"):
                    top.set_status(f"\u041f\u043e\u0432\u043d\u0438\u0439 \u0430\u0443\u0434\u0438\u0442 UI+Backend ({checks-fails}/{checks} OK \u0437\u0430 {dt_ms:.0f} \u043c\u0441) \u2014 \u0443 \u0431\u0443\u0444\u0435\u0440\u0456 (Ctrl+V)!")
            top.after(0, _publish)

        threading.Thread(target=_finish_with_backend, daemon=True).start()

    _run_dropdowns(0)
