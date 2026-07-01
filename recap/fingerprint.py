"""Runtime generation of realistic Windows/Chrome browser fingerprints.

Instead of shipping a single static profile, every solve draws a fresh,
internally-consistent fingerprint from weighted pools of real-world values.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field


# Recent stable Chrome majors seen in the wild.
_CHROME_MAJORS = [131, 132, 133, 134, 135, 136]

# (width, height) desktop resolutions with rough real-world weights.
_RESOLUTIONS = [
    ((1920, 1080), 40),
    ((1366, 768), 18),
    ((1536, 864), 12),
    ((1280, 720), 8),
    ((1600, 900), 7),
    ((2560, 1440), 9),
    ((1440, 900), 6),
]

# GPU vendor / ANGLE renderer pairs. Weighted toward common consumer hardware.
# Correlated desktop hardware profiles so GPU, core count, and deviceMemory
# stay internally consistent (an RTX 3060 with 4 cores / 4 GB is a red flag).
# Format: (gpu_vendor, gpu_renderer, core_choices, memory_choices, weight).
# NOTE: navigator.deviceMemory is spec-capped to {..,4,8}; Chrome never reports
# more than 8 regardless of real RAM, so memory choices stay within {4, 8}.
_HARDWARE_PROFILES = [
    ("Google Inc. (NVIDIA)",
     "ANGLE (NVIDIA, NVIDIA GeForce RTX 3060 (0x00002504) Direct3D11 vs_5_0 ps_5_0, D3D11)",
     [8, 12, 16], [8], 14),
    ("Google Inc. (NVIDIA)",
     "ANGLE (NVIDIA, NVIDIA GeForce GTX 1650 (0x00001F82) Direct3D11 vs_5_0 ps_5_0, D3D11)",
     [4, 6, 8], [8], 12),
    ("Google Inc. (Intel)",
     "ANGLE (Intel, Intel(R) UHD Graphics 620 (0x00003EA0) Direct3D11 vs_5_0 ps_5_0, D3D11)",
     [4, 8], [4, 8], 16),
    ("Google Inc. (Intel)",
     "ANGLE (Intel, Intel(R) Iris(R) Xe Graphics (0x00009A49) Direct3D11 vs_5_0 ps_5_0, D3D11)",
     [4, 8], [8], 14),
    ("Google Inc. (AMD)",
     "ANGLE (AMD, AMD Radeon RX 6600 Direct3D11 vs_5_0 ps_5_0, D3D11)",
     [6, 8, 12], [8], 8),
    ("Google Inc. (AMD)",
     "ANGLE (AMD, AMD Radeon(TM) Graphics Direct3D11 vs_5_0 ps_5_0, D3D11)",
     [4, 6, 8], [4, 8], 9),
]

# DPR options weighted per resolution: low-res laptop panels rarely run at a
# high device-pixel-ratio, high-res panels sometimes do. Keyed by (width, height).
_DPR_BY_RESOLUTION = {
    (1280, 720): [(1.0, 8), (1.25, 2)],
    (1366, 768): [(1.0, 9), (1.25, 1)],
    (1440, 900): [(1.0, 7), (1.25, 2), (1.5, 1)],
    (1536, 864): [(1.0, 6), (1.25, 3), (1.5, 1)],
    (1600, 900): [(1.0, 5), (1.25, 3), (1.5, 2)],
    (1920, 1080): [(1.0, 5), (1.25, 3), (1.5, 2), (2.0, 1)],
    (2560, 1440): [(1.0, 6), (1.25, 3), (1.5, 1)],
}
_DEFAULT_DPR = [(1.0, 6), (1.25, 3), (1.5, 2), (2.0, 1)]

_LOCALES = [
    (["en-US", "en"], "en-US", 55),
    (["en-GB", "en"], "en-GB", 15),
    (["en-US", "en", "es"], "en-US", 8),
    (["fr-FR", "fr", "en-US", "en"], "fr-FR", 7),
    (["de-DE", "de", "en-US", "en"], "de-DE", 7),
    (["pt-BR", "pt", "en-US", "en"], "pt-BR", 8),
]

_PLUGIN_SET = [
    "PDF Viewer", "Chrome PDF Viewer", "Chromium PDF Viewer",
    "Microsoft Edge PDF Viewer", "WebKit built-in PDF",
]

# SpeechSynthesis voices keyed by primary locale. Windows ships the Microsoft
# voices for the installed language; Chrome adds the online Google voices.
_VOICES_BY_LANG = {
    "en-US": [
        {"name": "Microsoft David - English (United States)", "lang": "en-US",
         "localService": True, "voiceURI": "Microsoft David - English (United States)"},
        {"name": "Microsoft Zira - English (United States)", "lang": "en-US",
         "localService": True, "voiceURI": "Microsoft Zira - English (United States)"},
        {"name": "Microsoft Mark - English (United States)", "lang": "en-US",
         "localService": True, "voiceURI": "Microsoft Mark - English (United States)"},
        {"name": "Google US English", "lang": "en-US",
         "localService": False, "voiceURI": "Google US English"},
    ],
    "en-GB": [
        {"name": "Microsoft George - English (United Kingdom)", "lang": "en-GB",
         "localService": True, "voiceURI": "Microsoft George - English (United Kingdom)"},
        {"name": "Microsoft Hazel - English (United Kingdom)", "lang": "en-GB",
         "localService": True, "voiceURI": "Microsoft Hazel - English (United Kingdom)"},
        {"name": "Google UK English Male", "lang": "en-GB",
         "localService": False, "voiceURI": "Google UK English Male"},
    ],
    "fr-FR": [
        {"name": "Microsoft Paul - French (France)", "lang": "fr-FR",
         "localService": True, "voiceURI": "Microsoft Paul - French (France)"},
        {"name": "Microsoft Hortense - French (France)", "lang": "fr-FR",
         "localService": True, "voiceURI": "Microsoft Hortense - French (France)"},
        {"name": "Google fran\u00e7ais", "lang": "fr-FR",
         "localService": False, "voiceURI": "Google fran\u00e7ais"},
    ],
    "de-DE": [
        {"name": "Microsoft Stefan - German (Germany)", "lang": "de-DE",
         "localService": True, "voiceURI": "Microsoft Stefan - German (Germany)"},
        {"name": "Microsoft Katja - German (Germany)", "lang": "de-DE",
         "localService": True, "voiceURI": "Microsoft Katja - German (Germany)"},
        {"name": "Google Deutsch", "lang": "de-DE",
         "localService": False, "voiceURI": "Google Deutsch"},
    ],
    "pt-BR": [
        {"name": "Microsoft Daniel - Portuguese (Brazil)", "lang": "pt-BR",
         "localService": True, "voiceURI": "Microsoft Daniel - Portuguese (Brazil)"},
        {"name": "Microsoft Maria - Portuguese (Brazil)", "lang": "pt-BR",
         "localService": True, "voiceURI": "Microsoft Maria - Portuguese (Brazil)"},
    ],
}
_FALLBACK_VOICES = _VOICES_BY_LANG["en-US"]  # locales without a specific voice set


@dataclass
class Fingerprint:
    """A single coherent browser identity."""

    user_agent: str
    chrome_major: int
    chrome_full: str
    platform: str
    languages: list[str]
    language: str
    screen: dict
    hardware_concurrency: int
    device_memory: int
    device_scale_factor: float
    max_touch_points: int
    gpu_vendor: str
    gpu_renderer: str
    plugins: list[str]
    voices: list[dict]
    battery: dict
    connection: dict
    # Filled in later once a proxy's geolocation is known.
    timezone: str | None = None
    tz_offset: int | None = None
    geolocation: dict | None = None
    sec_ch_ua: str = field(default="")

    def as_dict(self) -> dict:
        return {
            "userAgent": self.user_agent,
            "platform": self.platform,
            "languages": self.languages,
            "language": self.language,
            "screen": self.screen,
            "hardwareConcurrency": self.hardware_concurrency,
            "deviceMemory": self.device_memory,
            "maxTouchPoints": self.max_touch_points,
            "gpu": {"vendor": self.gpu_vendor, "renderer": self.gpu_renderer},
            "plugins": self.plugins,
            "voices": self.voices,
            "battery": self.battery,
            "connection": self.connection,
            "timezone": self.timezone,
            "tzOffset": self.tz_offset,
        }


def generate(seed: int | None = None) -> Fingerprint:
    """Produce a fresh, self-consistent Windows desktop Chrome fingerprint."""
    rng = random.Random(seed) if seed is not None else random
    _pick = lambda pool: _weighted_with(rng, pool)

    major = rng.choice(_CHROME_MAJORS)
    build = rng.randint(6000, 7100)
    patch = rng.randint(50, 190)
    full = f"{major}.0.{build}.{patch}"
    ua = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        f"(KHTML, like Gecko) Chrome/{major}.0.0.0 Safari/537.36"
    )

    (width, height) = _pick(_RESOLUTIONS)
    dpr = _pick(_DPR_BY_RESOLUTION.get((width, height), _DEFAULT_DPR))
    taskbar = rng.choice([40, 48, 56])
    chrome_ui = rng.choice([72, 79, 87])  # tabs + address bar height
    inner_w = width
    inner_h = height - taskbar - chrome_ui

    screen = {
        "width": width,
        "height": height,
        "availWidth": width,
        "availHeight": height - taskbar,
        "colorDepth": 24,
        "pixelDepth": 24,
        "innerWidth": inner_w,
        "innerHeight": max(inner_h, 400),
        "outerWidth": width,
        "outerHeight": height - taskbar,
        "orientationType": "landscape-primary",
        "orientationAngle": 0,
        "devicePixelRatio": dpr,
    }

    # Pick one coherent hardware profile, then draw a plausible core count and
    # deviceMemory value from within that profile's realistic ranges.
    gpu_vendor, gpu_renderer, core_choices, mem_choices = _pick(_HARDWARE_PROFILES)
    cores = rng.choice(core_choices)
    memory = rng.choice(mem_choices)
    languages, language = _pick(_LOCALES)

    # Voices correlated to the primary locale, plus the cross-locale Google
    # online voice (deduped so it never appears twice).
    voice_pool = _VOICES_BY_LANG.get(language, _FALLBACK_VOICES)
    seen_uris = {v["voiceURI"] for v in voice_pool}
    extra = [v for v in _FALLBACK_VOICES
             if not v["localService"] and v["voiceURI"] not in seen_uris]
    all_voices = voice_pool + extra
    count = min(rng.randint(3, 5), len(all_voices))
    voices = rng.sample(all_voices, k=count)
    for i, v in enumerate(voices):
        v = dict(v)
        v["default"] = i == 0
        voices[i] = v

    battery = {
        "charging": rng.random() < 0.6,
        "level": round(rng.uniform(0.35, 1.0), 2),
        "chargingTime": 0,
        "dischargingTime": None,
    }
    connection = {
        "effectiveType": rng.choice(["4g", "4g", "4g", "3g"]),
        "rtt": rng.choice([50, 100, 150]),
        "downlink": round(rng.uniform(5.0, 12.0), 1),
        "saveData": False,
        "type": "wifi",
    }

    sec_ch_ua = (
        f'"Chromium";v="{major}", "Google Chrome";v="{major}", '
        '"Not;A=Brand";v="99"'
    )

    return Fingerprint(
        user_agent=ua,
        chrome_major=major,
        chrome_full=full,
        platform="Win32",
        languages=languages,
        language=language,
        screen=screen,
        hardware_concurrency=cores,
        device_memory=memory,
        device_scale_factor=dpr,
        max_touch_points=0,
        gpu_vendor=gpu_vendor,
        gpu_renderer=gpu_renderer,
        plugins=list(_PLUGIN_SET),
        voices=voices,
        battery=battery,
        connection=connection,
        sec_ch_ua=sec_ch_ua,
    )


def _weighted_with(rng: random.Random, pool):
    weights = [p[-1] for p in pool]
    idx = rng.choices(range(len(pool)), weights=weights, k=1)[0]
    entry = pool[idx]
    return entry[:-1] if len(entry) > 2 else entry[0]
