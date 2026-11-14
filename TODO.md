# DiffAnyDoc — TODO

## Kurulum & Test Altyapısı

- [ ] **Python 3.13 uyumluluğu (`pyproject.toml`):** `rapidocr-onnxruntime>=1.3` bağımlılığına `; python_version < "3.13"` ortam belirteci eklemek veya ayrı bir `[ocr]` opsiyonel grubu tanımlamak; böylece Python 3.13+ üzerinde `pip install -e ".[web,desktop,dev]"` komutunun tek seferde hatasız çalışmasını sağlamak.
- [ ] **`dev` bağımlılıklarına `httpx` eklenmesi (`pyproject.toml`):** `tests/test_folder.py` ve `tests/test_report.py` içindeki FastAPI `TestClient` testlerinin ekstra kurulum gerektirmeden doğrudan çalışması için `dev` grubuna `httpx` eklemek.

## Yol Haritası (Yeni Özellikler)

- [x] **TASK-21 — Büyük Belge Performansı (Görünür Alan Öncelikli Lazy Sayfa Render):** 200+ sayfalık PDF/DOCX belgelerinde tüm sayfaları aynı anda yüklemek yerine `IntersectionObserver` (`rootMargin: "800px 0px"`) ile görünür alandaki ve yakın komşulardaki sayfaları öncelikli render etmek.
- [x] **TASK-22 — Taşınan Blok Tespiti (Move Detection):** Bir paragraf veya bölüm belgede başka bir konuma taşındığında "silindi + eklendi" yerine "taşındı" (`row.moved`) olarak algılayıp Adwaita vurgu rengiyle işaretlemek.
- [x] **TASK-23 — Sunum Formatları Desteği (`.pptx`, `.odp`):** Slayt metinleri, konuşmacı notları ve slayt etiketleri için saf stdlib tabanlı `PresentationAdapter` ve karşılaştırma desteği.
- [ ] **TASK-24 — E-posta & Arşiv Desteği (`.eml`, `.msg`, `.zip`):** E-posta gövdesi ve eklerini açıp karşılaştırma.
- [ ] **TASK-25 — Bölüm / Başlık (Outline) Gezintisi:** Uzun belgelerde başlık ağacı üzerinden değişiklik içeren bölümlere hızlı atlama.
- [ ] **TASK-26 — İşaretlenen Alanları (`Mark on page`) PDF Raporuna Aktarma:** Kullanıcının çizdiği kutucuk ve notları resmi PDF raporuna dahil etmek.
- [ ] **TASK-27 — Toplu (Batch) Klasör Karşılaştırma Çıktısı:** Klasör farklarını tek tıkla CSV veya toplu PDF raporu olarak dışa aktarmak.
- [ ] **TASK-28 — macOS Paketleme Desteği (`.app` / `.dmg`):** `tools/build.py` ve CI iş akışına macOS dağıtım hedefi eklemek.
