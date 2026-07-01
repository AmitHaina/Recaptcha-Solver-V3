# recap

A **Playwright-based reCAPTCHA v3 solver** with runtime browser-fingerprint rotation
and humanized interaction. It drives a real Chromium instance so Google's own
reCAPTCHA script collects a genuine, internally consistent fingerprint, which is
the only reliable way to earn a high v3 score.



---

## How it works

reCAPTCHA v3 never shows a puzzle. It silently collects ~50 environment and
behavioral signals, encrypts them, and posts them to Google, which returns a
score from `0.0` (bot) to `1.0` (human). `recap` maximizes that score by making
a real browser look like a real user:

```
generate fingerprint  ->  align timezone/geo to proxy  ->  launch Chromium
        ->  inject anti-detection init-script  ->  warm up browsing history
        ->  humanized mouse / scroll / focus  ->  grecaptcha.execute  ->  token
```

- **Fingerprint rotation**: correlated hardware profiles (GPU, cores, memory),
  resolution-matched DPR, locale-matched voices, screen, UA, battery.
- **Anti-detection patches**: canvas/WebGL noise, `storage.estimate`, enriched
  `chrome.runtime`, `mediaDevices`, all applied surgically to stay consistent
  with the signals reCAPTCHA actually hashes.
- **Humanized behavior**: bezier-curve mouse movement with entry sweep,
  decelerating scroll, real (trusted) clicks and focus, multi-step warmup.
- **Proxy aware**: timezone and geolocation are aligned to the proxy's IP.

---

## Install

```bash
pip install -r requirements.txt
playwright install chromium
```

Requires Python 3.10+.

---

## Usage

### As a library

```python
from recap import Recaptcha

token = Recaptcha(headless=True).solve(
    url="https://example.com/login",
    sitekey="6LcAbwIqAAAAAJvVAhSSJ8qzYsujc7kn1knmSgQX",
    action="submit",
)
print(token)
```

One-shot convenience wrapper:

```python
from recap import solve

token = solve(
    url="https://example.com/login",
    sitekey="6Lc...",
    action="submit",
    proxy="http://user:pass@host:port",   # optional
)
```

### Options

| Option           | Default    | Description                                            |
| ---------------- | ---------- | ------------------------------------------------------ |
| `proxy`          | `None`     | `http://user:pass@host:port` (timezone/geo align to it) |
| `headless`       | `True`     | Run Chromium headless                                  |
| `warmup`         | `True`     | Build a short browsing history before the target       |
| `debug`          | `False`    | Print per-stage timing                                 |
| `user_data_dir`  | `None`     | Persistent profile; cookies/trust accumulate over runs |
| `enterprise`     | `False`    | Use the enterprise `grecaptcha` API                    |

> Tip: a **residential proxy** plus a **persistent `user_data_dir`** raises the
> score the most, because Google's trust cookies build up across sessions.

### As an HTTP server

```bash
python server.py            # listens on 0.0.0.0:8778
```

**Synchronous solve:**

```bash
curl -X POST http://localhost:8778/solve \
  -H "Content-Type: application/json" \
  -d '{"url":"https://example.com","sitekey":"6Lc...","action":"submit"}'
```

**Async job:**

```bash
# enqueue -> returns {"job_id": "..."}
curl -X POST http://localhost:8778/jobs -H "Content-Type: application/json" \
  -d '{"url":"https://example.com","sitekey":"6Lc..."}'

# poll
curl http://localhost:8778/jobs/<job_id>
```

| Endpoint            | Method   | Description                    |
| ------------------- | -------- | ----------------------------- |
| `/solve`            | `POST`   | Synchronous solve, returns token |
| `/jobs`             | `POST`   | Enqueue an async solve        |
| `/jobs/{id}`        | `GET`    | Poll job state                |
| `/jobs/{id}`        | `DELETE` | Drop a finished job           |

---

## Project structure

```
Recaptchav3/
├── server.py            FastAPI front-end (sync + async jobs)
├── requirements.txt
└── recap/
    ├── engine.py        Recaptcha class + solve(): the browser flow
    ├── fingerprint.py   runtime fingerprint generation
    ├── patches.py       anti-detection init-script
    ├── location.py      proxy IP -> timezone/geo lookup
    └── network.py       proxy string parsing
```

---

## Contributing

Pull requests are welcome. To keep the solver consistent (reCAPTCHA punishes
*inconsistency* far more than any single "bad" value), please:

1. **Fork** the repo and create a feature branch.
2. Keep changes **surgical**: touch only what's needed, and make sure any
   fingerprint/patch change stays internally consistent (e.g. GPU must match the
   UA, `deviceMemory` must stay within spec).
3. In your PR description, **explain what you changed and why**: which signal it
   affects and how you verified it doesn't create a detectable mismatch.

---

## Issues & community

Found a bug, a detection tell, or a score regression? Open an issue with the
details, or join the Discord:

[![Discord](https://img.shields.io/badge/Discord-Join%20Server-5865F2?style=for-the-badge&logo=discord&logoColor=white)](https://discord.gg/QphWRKHvH2)

---

## Disclaimer

This project is for educational and research purposes. You are responsible for
complying with the terms of service of any site you interact with.
