# Static reproduction

Interpreter: C:\Users\16173\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe
Working directory: C:\Users\16173\Documents\ChatGPT\人工智能+

Run validate_package.py then validate_official.py with this interpreter and -B; neither is an integration runner. Authoring build_official.py is one-shot and aborts if SOURCE_LOCK exists. Original directory creation used New-Item -ErrorAction Stop after absence check. Build and validation use only standard library plus already installed Pydantic; no dependency installation. validate_package raw stdout and validate_official appended stdout are retained in VALIDATION_LOG.txt. Supplementary reference-state tests do not exercise actual DB persistence, threads or processes.

```powershell
& 'C:\Users\16173\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -B 'C:\Users\16173\Documents\ChatGPT\人工智能+\space-m1-m2-v12-supervisor\reports\M1_M2_OFFICIAL_PROTOCOL_V1_0_FINAL_20261113\validate_package.py'
& 'C:\Users\16173\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -B 'C:\Users\16173\Documents\ChatGPT\人工智能+\space-m1-m2-v12-supervisor\reports\M1_M2_OFFICIAL_PROTOCOL_V1_0_FINAL_20261113\validate_official.py'
```

Finalizer is exclusive: do not rerun over this delivered ZIP. It recomputes input/source hashes and preservation, emits the report/Manifest, creates the ZIP using mode x, and verifies every archived byte and path. Its stdout supplies final file count, Manifest SHA256 and archive SHA256. Do not redirect finalizer stdout into the directory after its manifest is sealed.
