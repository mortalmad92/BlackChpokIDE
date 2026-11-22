# Тимчасова перевірка: чи експортує llama.dll API для зору (mtmd/clip).
import ctypes
import os

path = r"C:\AI\blackchpock_ai\userdata\runtime\llama.dll"
os.add_dll_directory(os.path.dirname(path))
lib = ctypes.WinDLL(path)
names = [
    "llama_chat_apply_template",
    "mtmd_init_from_file", "mtmd_free", "mtmd_default_marker",
    "mtmd_load_prompt_template", "mtmd_bitmap_init_from_file",
    "mtmd_bitmap_init", "mtmd_bitmap_free", "mtmd_bitmap_get_nx",
    "mtmd_tokenize", "mtmd_helper_eval_chunks", "mtmd_helper_get_n_tokens",
]
for name in names:
    print(f"{name:32s} {bool(getattr(lib, name, None))}")
