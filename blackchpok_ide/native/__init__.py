"""BLACKCHPOK NATIVE INFERENCE ENGINE — власний рушій локальних моделей.

Пакет дає IDE можливість САМІЙ виконувати GGUF-моделі: без LM Studio,
Ollama, Jan чи GPT4All і без окремого серверного процесу.

Склад (кожен модуль — окрема відповідальність):

``_abi``        C-структури llama.cpp, описані для ctypes
``_bindings``   завантаження llama.dll/ggml.dll, перевірка ABI, пристрої
``gguf``        читання метаданих GGUF (до завантаження ваг)
``_quant``      назви quantization і біти на вагу
``inspect``     діагностика моделі + прогноз RAM/VRAM/шарів
``tokenizer``   реальний tokenizer моделі (не оцінка по символах)
``sampling``    параметри семплінгу й побудова ланцюжка семплерів
``chatfmt``     шаблони чату й адаптер tool calling
``kv``          керування KV-кешем (скидання, переиспользование префікса)
``engine``      життєвий цикл моделі, генерація, streaming, скасування
``embeddings``  локальні вектори через ту саму модель
``manager``     менеджер моделей: список, інспекція, завантаження, видалення
``api``         Runtime API для решти IDE (єдина точка входу)

Імпорт пакета навмисно дешевий: важкі бібліотеки вантажаться ліниво, коли
справді потрібен інференс. Інакше старт IDE платив би за рушій щоразу.
"""

from __future__ import annotations

__all__ = [
    "NativeUnavailable",
    "library_ready",
]

from ._bindings import NativeUnavailable, library_ready
