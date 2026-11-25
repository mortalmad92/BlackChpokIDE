# BlackChpok IDE 2.0

**Локальне автономне AI-середовище розробки нового покоління (2026)** з гібридним інтелектом (`Local LLM + Cloud Gemini`), довгостроковою пам'яттю **NEUROMESH**, вбудованим браузером **Live Preview** та кросплатформеною підтримкою **Windows і Linux**.

---

## Ключові можливості

- **Гібридний конвеєр кодування (`NEUROMESH -> Gemini Architect 2026 -> Local Coder`)**: локальний запуск GGUF-моделей (`llama.cpp` / CUDA / Vulkan / CPU) + підготовка архітектури 2026 року через **Google Gemini**.
- **Безкінечна сесія (NEUROMESH + RAG)**: автоматичне звільнення контекстного вікна зі збереженням досвіду у довгострокову пам'ять.
- **Автономний та Нічний режими (`Autonomous & Night Shift`)**: самостійний пошук ідей розвитку проєкту (локально, через Gemini або в мережі), керування чергою та інкрементальне допрацювання коду.
- **Вбудований `Live Preview` та CLI-термінал**: адаптивна темна тема браузера, збереження сесії GitHub, створення `.venv` і встановлення бібліотек у папці проєкту.
- **Розумна синхронізація з GitHub (`Smart Git Auto-Sync`)**: ізольована прив'язка Git до кожної папки проєкту та авто-пуш лише при суттєвих змінах.
- **Повна портативність і захист ядра IDE**: робота з будь-якої папки на **Windows** та **Linux**, ізоляція проєктів у `~/BlackChpokProjects`.

---

## Встановлення та запуск

### Windows
```bat
git clone https://github.com
cd BlackChpokIDE
install.bat
run_ide.bat
```

### Linux (Ubuntu / Debian / Arch)
```bash
sudo apt update && sudo apt install -y python3 python3-venv python3-tk git
git clone https://github.com
cd BlackChpokIDE
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python main.py
```

---

## Тестування

```bash
python tests/check_style.py
python main.py --selftest
python -m unittest discover -s tests
```
