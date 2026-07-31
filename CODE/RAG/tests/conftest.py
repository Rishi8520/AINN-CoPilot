import sys
from pathlib import Path


RAG_ROOT = Path(__file__).resolve().parents[1]
rag_root_text = str(RAG_ROOT)
if rag_root_text not in sys.path:
    sys.path.insert(0, rag_root_text)

for module_name in list(sys.modules):
    if module_name == "app" or module_name.startswith("app."):
        module = sys.modules[module_name]
        module_file = getattr(module, "__file__", "") or ""
        if rag_root_text not in module_file:
            sys.modules.pop(module_name, None)
