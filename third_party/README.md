# Third-Party Sources

## MediaCrawler

`third_party/MediaCrawler` is vendored source used by the optional Xiaohongshu backend:

```bash
WORKER_ADAPTER=mediacrawler python -m apps.worker --once
```

Runtime dependencies are intentionally not committed. Install them locally with:

```bash
python3.12 -m venv third_party/MediaCrawler/.venv
third_party/MediaCrawler/.venv/bin/pip install -r third_party/MediaCrawler/requirements.txt
```

Do not commit browser profiles, runtime data, logs, `.venv`, cookies, or generated crawler outputs.
