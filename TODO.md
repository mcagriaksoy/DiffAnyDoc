# DiffAnyDoc — TODO

## Kurulum & Test Altyapısı

- [ ] **Python 3.13 uyumluluğu (`pyproject.toml`):** `rapidocr-onnxruntime>=1.3` bağımlılığına `; python_version < "3.13"` ortam belirteci eklemek veya ayrı bir `[ocr]` opsiyonel grubu tanımlamak; böylece Python 3.13+ üzerinde `pip install -e ".[web,desktop,dev]"` komutunun tek seferde hatasız çalışmasını sağlamak.
- [ ] **`dev` bağımlılıklarına `httpx` eklenmesi (`pyproject.toml`):** `tests/test_folder.py` ve `tests/test_report.py` içindeki FastAPI `TestClient` testlerinin ekstra kurulum gerektirmeden doğrudan çalışması için `dev` grubuna `httpx` eklemek.
