# Privacy Policy

DiffAnyDoc is designed with a strict **privacy-first, local-only** architecture.

## 1. 100% Offline Document Processing
All document parsing, text extraction, OCR (via embedded RapidOCR or local Tesseract),
pixel registration, and comparison reports run entirely on your own machine.
No document files, extracted text, images, or comparison results are ever
uploaded or transmitted over the network.

## 2. Zero Telemetry or Analytics
DiffAnyDoc does not collect usage analytics, crash telemetry, tracking cookies,
or hardware/device identifiers.

## 3. Local Caches
To speed up repeated comparisons, DiffAnyDoc may store an OCR text cache on your
local disk keyed by the SHA-256 hash of the file content. You can delete this
cache at any time.

## 4. Optional User-Triggered Update Checks
DiffAnyDoc only makes an outbound network request when you explicitly click
**Check for Updates** in the application menu and press **Check now**. That
request queries public GitHub Releases (`https://api.github.com/repos/mcagriaksoy/DiffAnyDoc/releases/latest`)
and sends no document data or user identifiers.

