# Збірка BlackChpok IDE у .exe

## Швидко

```bat
build_exe.bat
```

Скрипт сам: перевіряє Python, ставить PyInstaller (через `pip`, а якщо pip
заблокований — через `tools\fetch_wheels.py`), проганяє самоперевірку коду,
генерує іконку і збирає `dist\BlackChpok.exe`.

Результат: **один файл** `dist\BlackChpok.exe`, без консолі, з іконкою.

---

## Вручну

```powershell
.\.venv\Scripts\python.exe -m PyInstaller --noconfirm --clean BlackChpokIDE.spec
```

Корисні варіанти:

```powershell
# швидка збірка без spec-файлу
.\.venv\Scripts\python.exe -m PyInstaller --onefile --windowed --name BlackChpok main.py

# папка замість одного файлу (стартує швидше, менше проблем з антивірусом)
.\.venv\Scripts\python.exe -m PyInstaller --onedir --windowed --name BlackChpok main.py
```

Для onedir у `BlackChpokIDE.spec` достатньо додати `COLLECT`:

```python
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="BlackChpok", console=False, icon=...)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="BlackChpok")
```

---

## Перевірка зібраного файлу

```bat
dist\BlackChpok.exe --selftest
dist\BlackChpok.exe --version
dist\BlackChpok.exe "C:\AI\blackchpock_ai"
```

`--selftest` не відкриває вікно: перевіряє налаштування, інструменти, безпеку
шляхів, підсвітку й пошук, друкує результат і повертає код 0 або 1.
У збірці без консолі вивід іде у `%APPDATA%\BlackChpokIDE\console.log`.

Для перевірки, що вікно справді відкривається:

```powershell
.\.venv\Scripts\python.exe tests\check_exe.py dist\BlackChpok.exe
```

---

## Якщо немає мережі

PyInstaller можна поставити без `pip` — розпакуванням wheel-файлів:

```powershell
.\.venv\Scripts\python.exe tools\fetch_wheels.py pyinstaller altgraph pefile pywin32-ctypes setuptools
```

Скрипт бере wheel з PyPI, розпаковує у `site-packages` і не виконує код пакетів.
Перевірка: `.venv\Scripts\python.exe -m PyInstaller --version`.

---

## Що саме потрапляє в .exe

- Пакет `blackchpok_ide` (усі модулі перелічені в `hiddenimports`).
- `assets\icon.ico` і `assets\icon.png`.
- `README_UK.md` (довідка).
- `vibe_router`, `rag_engine`, `agent_tools`, `night_shift` — якщо лежать поруч
  у корені репозиторію (spec додає їх автоматично).

Не потрапляють (свідомо, щоб не роздувати файл): `numpy`, `pandas`, `PySide6`,
`playwright`, `pymupdf`, `pikepdf`, `pypdf`, `docx`, `pytest`.

---

## Часті помилки збірки

| Помилка | Причина / рішення |
| --- | --- |
| `PermissionError: dist\BlackChpok.exe` | попередній .exe ще запущений — закрий процес `BlackChpok` |
| `Failed to extract VCRUNTIME140.dll` | антивірус блокує розпакування в `%TEMP%`; додай виняток або збери `--onedir` |
| `PyInstaller недоступний` | немає мережі/прав: `tools\fetch_wheels.py pyinstaller ...` |
| `ModuleNotFoundError: blackchpok_ide` | запускай PyInstaller з кореня репозиторію і через spec-файл |
| `tkinter` не знайдено | Python поставлено без Tcl/Tk — перевстанови з python.org (галочка tcl/tk) |

---

## Розмір і швидкість

- Один файл ≈ 14 МБ.
- Перший запуск 1–3 с (розпакування в `%TEMP%\_MEI*`).
- `--onedir` стартує швидше і не потребує запису в `%TEMP%`.
