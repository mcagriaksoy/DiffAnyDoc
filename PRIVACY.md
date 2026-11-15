# Privacy Policy

DiffAnyDoc is engineered with a strict **privacy-first, 100% local-only** architecture suitable for confidential legal, financial, engineering, and enterprise documents.

## 1. 100% Offline Document Processing
All document parsing, text extraction, OCR (via embedded RapidOCR or local Tesseract), pixel registration, X-Ray overlay rendering, and comparison reports run entirely on your own machine. No document files, extracted text, images, or comparison results are ever uploaded or transmitted over the network.

## 2. 100% Offline Local AI Semantic Analysis
When you use the **✨ AI** semantic comparison feature, inference runs strictly on your local hardware (`127.0.0.1`) via `llamafile` and local GGUF model weights. No prompts, document snippets, or comparison digests are ever sent to OpenAI, Anthropic, Google, or any external cloud AI service.

## 3. Zero Telemetry or Analytics
DiffAnyDoc does not embed tracking scripts, usage analytics, crash telemetry, advertising SDKs, or hardware/device fingerprinting.

## 4. Local Caches & Storage
To speed up repeated comparisons, DiffAnyDoc stores:
- An local OCR text cache keyed by the SHA-256 hash of the file content (`~/.cache/diffanydoc/ocr` on Linux, `%LOCALAPPDATA%\DiffAnyDoc\cache\ocr` on Windows).
- Optional downloaded GGUF AI models and the `llamafile` binary (`~/.cache/diffanydoc/ai` on Linux, `%LOCALAPPDATA%\DiffAnyDoc\cache\ai` on Windows).

You can inspect or delete these local directories at any time.

## 5. Optional User-Triggered Network Requests
DiffAnyDoc never makes background network connections on startup. Outbound requests occur only when explicitly triggered by you:
1. **Check for Updates**: Clicking **Check now** in the Updates dialog queries public GitHub Releases (`https://api.github.com/repos/mcagriaksoy/DiffAnyDoc/releases/latest`) without sending any user or document identifiers.
2. **One-Time Local AI Model Download**: Clicking **Download & Set Up** in the Local AI tab or Settings downloads the Apache-2.0 `llamafile` binary from Mozilla-Ocho GitHub Releases and the selected Apache-2.0 GGUF model from Hugging Face to your local cache directory. Once downloaded, AI analysis works completely offline without an internet connection.
