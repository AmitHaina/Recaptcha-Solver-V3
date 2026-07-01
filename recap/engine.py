"""Playwright-based reCAPTCHA v3 token harvester.

Flow: generate a fingerprint -> (optional) align timezone/geo to the proxy ->
launch Chromium -> emulate the identity via native context options + an
init-script -> warm up -> act human -> call grecaptcha.execute -> return token.
"""
from __future__ import annotations

import asyncio
import random
import re
import time
import zlib

from playwright.async_api import async_playwright

from . import location, patches
from .fingerprint import Fingerprint, generate
from .network import parse

# reCAPTCHA v3 posts here; the response body carries the token as "rresp","<t>".
_RELOAD_RE = re.compile(r"/recaptcha/(api2|enterprise)/reload")
_TOKEN_RE = re.compile(r'"rresp","(.*?)"')

_LAUNCH_ARGS = [
    "--disable-blink-features=AutomationControlled",
    "--no-first-run",
    "--no-default-browser-check",
    "--disable-infobars",
    "--disable-ipc-flooding-protection",
    "--disable-features=IsolateOrigins,site-per-process",
    "--use-mock-keychain",
    # Stop WebRTC from ever using a non-proxied path, so no ICE candidate can
    # expose the real IP behind the proxy. RTCPeerConnection itself stays
    # present and native, matching a real Chrome fingerprint.
    "--force-webrtc-ip-handling-policy=disable_non_proxied_udp",
]

# Each entry is (domain, [paths]); the browser visits the domain root then each
# path in turn, building a short, plausible browsing history before the target.
_WARMUP_SEQUENCES = [
    ("google.com", ["", "search?q=weather"]),
    ("youtube.com", [""]),
    ("google.com", ["", "search?q=news"]),
    ("google.com", ["", "search?q=translate"]),
]


class Recaptcha:
    """Reusable solver. One instance can solve many targets sequentially."""

    def __init__(
        self,
        proxy: str | None = None,
        headless: bool = True,
        warmup: bool = True,
        debug: bool = False,
        user_data_dir: str | None = None,
    ):
        self.proxy = parse(proxy)
        self.headless = headless
        self.warmup = warmup
        self.debug = debug
        self.user_data_dir = user_data_dir
        # A persistent profile keeps a stable identity across runs; derive a
        # fixed fingerprint seed from its path so the UA/screen/GPU don't drift
        # while its cookies accumulate. Fresh sessions rotate freely (seed=None).
        self._seed = zlib.crc32(user_data_dir.encode()) if user_data_dir else None

    async def asolve(
        self,
        url: str,
        sitekey: str,
        action: str = "submit",
        enterprise: bool = False,
    ) -> str:
        clock = time.perf_counter
        marks: dict[str, float] = {}
        start = clock()
        fp = generate(seed=self._seed)
        geo = await self._geo(fp)
        marks["setup"] = clock() - start

        async with async_playwright() as pw:
            t = clock()
            browser, context = await self._start(pw, fp, geo)
            marks["launch"] = clock() - t
            try:
                t = clock()
                await context.add_init_script(patches.build(fp))
                page = context.pages[0] if context.pages else await context.new_page()

                # Fallback path (borrowed from Playwright-reCAPTCHA): passively
                # scrape the token from the /reload response the page produces,
                # in case the active grecaptcha.execute call fails.
                captured: dict[str, str | None] = {"token": None}
                page.on("response", lambda r: self._capture(r, captured))
                marks["context"] = clock() - t

                if self.warmup:
                    t = clock()
                    await self._warmup(page)
                    marks["warmup"] = clock() - t

                t = clock()
                await page.goto(url, wait_until="domcontentloaded")
                marks["goto"] = clock() - t

                await self._simulate_focus(page)

                t = clock()
                await self._humanize(page)
                marks["humanize"] = clock() - t

                t = clock()
                token = await self._execute(page, sitekey, action, enterprise, captured)
                marks["execute"] = clock() - t
                return token
            finally:
                await self._shutdown(context, browser)
                if self.debug:
                    breakdown = " ".join(f"{k}={v:.1f}s" for k, v in marks.items())
                    print(f"[recap] {breakdown} | total={clock() - start:.1f}s")

    @staticmethod
    async def _shutdown(context, browser) -> None:
        """Tear down the context/browser without letting a wedged Chromium IPC
        stall the worker. Each close is time-bounded; on timeout we bail out so
        the concurrency slot is released, and `async_playwright`'s exit reaps the
        orphaned browser process when the driver shuts down.
        """
        try:
            await asyncio.wait_for(context.close(), timeout=5.0)
        except Exception:
            pass
        if browser is not None:
            try:
                await asyncio.wait_for(browser.close(), timeout=5.0)
            except Exception:
                pass

    def solve(
        self,
        url: str,
        sitekey: str,
        action: str = "submit",
        enterprise: bool = False,
    ) -> str:
        return asyncio.run(self.asolve(url, sitekey, action, enterprise))

    # -- internals --------------------------------------------------------

    async def _geo(self, fp: Fingerprint) -> dict | None:
        """Look up the proxy's location and fold timezone into the fingerprint."""
        if not self.proxy:
            return None
        geo = await asyncio.to_thread(location.lookup, self.proxy.url)
        if not geo:
            return None
        if geo.get("timezone"):
            fp.timezone = geo["timezone"]
            fp.tz_offset = geo.get("tz_offset")
        return geo

    async def _start(self, pw, fp: Fingerprint, geo: dict | None):
        """Launch the browser and return (browser_or_None, context).

        With a user_data_dir we use a persistent context so cookies/history
        survive between solves (raises v3 trust); otherwise a fresh, isolated
        context that rotates every run.
        """
        opts = self._context_opts(fp, geo)
        proxy = self.proxy.playwright() if self.proxy else None
        if self.user_data_dir:
            context = await pw.chromium.launch_persistent_context(
                self.user_data_dir,
                headless=self.headless,
                args=_LAUNCH_ARGS,
                proxy=proxy,
                **opts,
            )
            return None, context
        browser = await pw.chromium.launch(
            headless=self.headless, args=_LAUNCH_ARGS, proxy=proxy
        )
        context = await browser.new_context(**opts)
        return browser, context

    def _context_opts(self, fp: Fingerprint, geo: dict | None) -> dict:
        s = fp.screen
        opts = dict(
            user_agent=fp.user_agent,
            locale=fp.language,
            viewport={"width": s["innerWidth"], "height": s["innerHeight"]},
            screen={"width": s["width"], "height": s["height"]},
            device_scale_factor=fp.device_scale_factor,
            color_scheme="light",
            is_mobile=False,
            has_touch=False,
            extra_http_headers={
                "sec-ch-ua": fp.sec_ch_ua,
                "sec-ch-ua-mobile": "?0",
                "sec-ch-ua-platform": '"Windows"',
                "accept-language": ",".join(
                    lang if i == 0 else f"{lang};q={max(0.1, 1.0 - i * 0.1):.1f}"
                    for i, lang in enumerate(fp.languages)
                ),
            },
        )
        if geo and geo.get("timezone"):
            opts["timezone_id"] = geo["timezone"]
        if geo and geo.get("lat") is not None and geo.get("lon") is not None:
            opts["geolocation"] = {
                "latitude": float(geo["lat"]),
                "longitude": float(geo["lon"]),
                "accuracy": 100,
            }
            opts["permissions"] = ["geolocation"]
        return opts

    async def _warmup(self, page) -> None:
        """Multi-step warmup that builds a realistic history before the target."""
        domain, paths = random.choice(_WARMUP_SEQUENCES)

        # Warmup only needs the navigation + behavior, not the pixels. Drop
        # heavy resources so these pages settle fast; the real target page is
        # never routed, so its fingerprint is unaffected.
        async def _block(route):
            if route.request.resource_type in ("image", "media", "font"):
                await route.abort()
            else:
                await route.continue_()

        await page.route("**/*", _block)
        try:
            for i, path in enumerate(paths):
                try:
                    url = f"https://www.{domain}/{path}"
                    await page.goto(url, wait_until="commit", timeout=15000)
                    await page.wait_for_timeout(random.randint(1500, 3000))
                    await self._humanize(page)
                    # Linger a little longer on the final page, as people do.
                    if i == len(paths) - 1:
                        await page.wait_for_timeout(random.randint(1000, 2000))
                except Exception:
                    continue
        finally:
            await page.unroute("**/*", _block)

    async def _simulate_focus(self, page) -> None:
        """Ensure the tab is genuinely focused/visible before interacting.

        Uses bring_to_front rather than dispatching a synthetic FocusEvent: a
        dispatched event is isTrusted=false (a detection red flag) and would not
        change document.hasFocus()/visibilityState anyway. bring_to_front sets
        real focus at the browser level, so those checks reflect a live user.
        """
        await page.wait_for_timeout(random.randint(100, 500))
        try:
            await page.bring_to_front()
        except Exception:
            pass
        await page.wait_for_timeout(random.randint(50, 200))

    async def _humanize(self, page) -> None:
        """Curved cursor movement + scroll via the input pipeline, not fake events."""
        size = page.viewport_size or {"width": 1280, "height": 720}

        # Playwright's cursor starts at (0, 0); begin there and sweep into the
        # viewport so the first move is a natural entry, not a teleport to centre.
        x, y = 0, 0
        entry_x = random.randint(size["width"] // 3, size["width"] // 2)
        entry_y = random.randint(size["height"] // 4, size["height"] // 2)
        await self._bezier_move(page, x, y, entry_x, entry_y)
        x, y = entry_x, entry_y
        await page.wait_for_timeout(random.randint(300, 600))

        for _ in range(random.randint(3, 6)):
            target_x = max(50, min(size["width"] - 50, x + random.uniform(-200, 200)))
            target_y = max(50, min(size["height"] - 50, y + random.uniform(-150, 150)))
            await self._bezier_move(page, x, y, target_x, target_y)
            x, y = target_x, target_y
            # Natural pause - humans stop to "read".
            await page.wait_for_timeout(random.randint(200, 800))
        await self._natural_scroll(page, direction=1)

    async def _natural_scroll(self, page, direction=1) -> None:
        """Scroll a short distance with realistic deceleration."""
        total = random.randint(300, 600) * direction
        velocity = random.uniform(80, 150)
        scrolled = 0
        while abs(scrolled) < abs(total):
            chunk = int(velocity) * direction
            # Deceleration eventually rounds the chunk to nothing; stop before
            # that turns into an infinite loop and finish the remaining distance.
            if abs(chunk) < 5:
                await page.mouse.wheel(0, total - scrolled)
                break
            await page.mouse.wheel(0, chunk)
            scrolled += chunk
            velocity *= random.uniform(0.85, 0.92)
            await page.wait_for_timeout(random.randint(15, 35))
        # Occasionally nudge back up, the way people overshoot and correct.
        if random.random() < 0.3:
            await page.mouse.wheel(0, -random.randint(30, 80))
            await page.wait_for_timeout(random.randint(200, 400))

    async def _bezier_move(self, page, x1, y1, x2, y2, steps=None) -> None:
        """Move the cursor along a cubic Bezier curve with easing at the ends."""
        if steps is None:
            dist = ((x2 - x1) ** 2 + (y2 - y1) ** 2) ** 0.5
            steps = max(8, int(dist / 15))
        # Randomised control points give each path a unique, non-linear shape.
        cx1 = x1 + (x2 - x1) * random.uniform(0.2, 0.4) + random.uniform(-30, 30)
        cy1 = y1 + (y2 - y1) * random.uniform(0.2, 0.4) + random.uniform(-30, 30)
        cx2 = x1 + (x2 - x1) * random.uniform(0.6, 0.8) + random.uniform(-30, 30)
        cy2 = y1 + (y2 - y1) * random.uniform(0.6, 0.8) + random.uniform(-30, 30)
        for i in range(steps + 1):
            t = i / steps
            mt = 1 - t
            px = mt ** 3 * x1 + 3 * mt ** 2 * t * cx1 + 3 * mt * t ** 2 * cx2 + t ** 3 * x2
            py = mt ** 3 * y1 + 3 * mt ** 2 * t * cy1 + 3 * mt * t ** 2 * cy2 + t ** 3 * y2
            await page.mouse.move(px, py)
            # Variable speed - slower at the start/end, faster through the middle.
            if t < 0.2 or t > 0.8:
                await page.wait_for_timeout(random.randint(8, 16))
            else:
                await page.wait_for_timeout(random.randint(3, 8))

    async def _capture(self, response, captured: dict) -> None:
        """Scrape the g-recaptcha-response token from a /reload response body."""
        if captured["token"] or not _RELOAD_RE.search(response.url):
            return
        try:
            match = _TOKEN_RE.search(await response.text())
        except Exception:
            return
        if match:
            captured["token"] = match.group(1)

    async def _safe_click(self, page) -> None:
        """Click empty space near the centre for a real user gesture.

        Skips the click if the point lands on a link/button/form control so it
        cannot navigate away from the target page or submit a form, either of
        which would drop grecaptcha and break the solve.
        """
        size = page.viewport_size or {"width": 1280, "height": 720}
        x = size["width"] // 2 + random.randint(-100, 100)
        y = size["height"] // 2 + random.randint(-50, 50)
        try:
            safe = await page.evaluate(
                """([x, y]) => {
                    const el = document.elementFromPoint(x, y);
                    if (!el) return true;
                    return !el.closest('a,button,input,textarea,select,label,summary,[onclick],[role="button"],[role="link"]');
                }""",
                [x, y],
            )
            if safe:
                await page.mouse.click(x, y)
        except Exception:
            pass

    async def _execute(self, page, sitekey, action, enterprise, captured) -> str:
        # A short pause plus a genuine click give reCAPTCHA a real user gesture
        # (transient activation) right before the token request, the way a
        # person acts on the page rather than firing execute instantly.
        await page.wait_for_timeout(random.randint(500, 1500))
        await self._safe_click(page)
        await page.wait_for_timeout(random.randint(200, 500))

        api = "grecaptcha.enterprise" if enterprise else "grecaptcha"
        try:
            token = await page.evaluate(
                """
                ([api, sitekey, action]) => new Promise((resolve, reject) => {
                    const g = api === 'grecaptcha.enterprise'
                        ? window.grecaptcha.enterprise : window.grecaptcha;
                    g.ready(() => {
                        g.execute(sitekey, { action }).then(resolve).catch(reject);
                    });
                })
                """,
                [api, sitekey, action],
            )
            if token:
                return token
        except Exception:
            pass  # fall through to the passively captured token

        if captured["token"]:
            return captured["token"]
        raise RuntimeError("failed to obtain reCAPTCHA token")


def solve(
    url: str,
    sitekey: str,
    action: str = "submit",
    enterprise: bool = False,
    *,
    proxy: str | None = None,
    headless: bool = True,
    warmup: bool = True,
    debug: bool = False,
    user_data_dir: str | None = None,
) -> str:
    """One-shot convenience wrapper."""
    return Recaptcha(
        proxy=proxy,
        headless=headless,
        warmup=warmup,
        debug=debug,
        user_data_dir=user_data_dir,
    ).solve(url, sitekey, action, enterprise)
