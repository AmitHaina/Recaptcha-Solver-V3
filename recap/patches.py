"""Builds the anti-detection init-script injected before any page script runs.

The JavaScript lives here as a Python template rather than a standalone .js
file. `build(fp)` serialises a fingerprint into the template so every browser
context gets a distinct, coherent identity.
"""
from __future__ import annotations

import json

from .fingerprint import Fingerprint


# Template. `__PROFILE__` is replaced with the JSON fingerprint at build time.
_TEMPLATE = r"""
(() => {
  const P = __PROFILE__;

  // Redefine a property with a stable getter, swallowing failures silently.
  const mask = (obj, prop, value) => {
    try {
      Object.defineProperty(obj, prop, { get: () => value, configurable: true });
    } catch (_) {}
  };
  // Make a patched function stringify like the native one it replaces.
  const spoofToString = (patched, original) => {
    try { patched.toString = original.toString.bind(original); } catch (_) {}
    return patched;
  };

  // --- automation flags -------------------------------------------------
  mask(navigator, 'webdriver', undefined);

  // --- window.chrome ----------------------------------------------------
  if (!window.chrome) {
    const perfNav = () => performance.timing || {};
    Object.defineProperty(window, 'chrome', {
      configurable: true, writable: true,
      value: {
        app: {
          isInstalled: false,
          InstallState: { DISABLED: 'disabled', INSTALLED: 'installed', NOT_INSTALLED: 'not_installed' },
          RunningState: { CANNOT_RUN: 'cannot_run', READY_TO_RUN: 'ready_to_run', RUNNING: 'running' },
        },
        runtime: {
          connect: (extensionId, connectInfo) => ({
            onMessage: { addListener() {}, removeListener() {}, hasListeners() { return false; } },
            onDisconnect: { addListener() {}, removeListener() {} },
            postMessage() {}, disconnect() {},
            sender: null,
            name: (connectInfo && connectInfo.name) || '',
          }),
          sendMessage: () => Promise.resolve(),
          id: undefined,
          OnInstalledReason: { CHROME_UPDATE: 'chrome_update', INSTALL: 'install', SHARED_MODULE_UPDATE: 'shared_module_update', UPDATE: 'update' },
          OnRestartRequiredReason: { APP_UPDATE: 'app_update', OS_UPDATE: 'os_update', PERIODIC: 'periodic' },
          PlatformOs: { ANDROID: 'android', CROS: 'cros', LINUX: 'linux', MAC: 'mac', OPENBSD: 'openbsd', WIN: 'win' },
          PlatformArch: { ARM: 'arm', ARM64: 'arm64', MIPS: 'mips', MIPS64: 'mips64', X86_32: 'x86-32', X86_64: 'x86-64' },
          PlatformNaclArch: { ARM: 'arm', MIPS: 'mips', MIPS64: 'mips64', X86_32: 'x86-32', X86_64: 'x86-64' },
          RequestUpdateCheckStatus: { NO_UPDATE: 'no_update', THROTTLED: 'throttled', UPDATE_AVAILABLE: 'update_available' },
        },
        loadTimes: () => {
          const t = perfNav();
          return {
            requestTime: (t.navigationStart || Date.now()) / 1000,
            startLoadTime: (t.navigationStart || Date.now()) / 1000,
            commitLoadTime: (t.responseStart || Date.now()) / 1000,
            finishDocumentLoadTime: (t.domContentLoadedEventEnd || Date.now()) / 1000,
            finishLoadTime: (t.loadEventEnd || Date.now()) / 1000,
            firstPaintTime: (t.responseEnd || Date.now()) / 1000,
            firstPaintAfterLoadTime: 0,
            navigationType: 'Other',
            wasFetchedViaSpdy: true, wasNpnNegotiated: true,
            npnNegotiatedProtocol: 'h2', connectionInfo: 'h2',
          };
        },
        csi: () => ({
          startE: (perfNav().navigationStart || Date.now()),
          onloadT: Date.now(),
          pageT: Date.now() - (perfNav().navigationStart || Date.now()),
          tran: 15,
        }),
      },
    });
  }

  // --- navigator core ---------------------------------------------------
  mask(navigator, 'platform', P.platform);
  mask(navigator, 'hardwareConcurrency', P.hardwareConcurrency);
  mask(navigator, 'deviceMemory', P.deviceMemory);
  mask(navigator, 'maxTouchPoints', P.maxTouchPoints);
  mask(navigator, 'languages', Object.freeze(P.languages.slice()));
  mask(navigator, 'language', P.language);
  mask(navigator, 'vendor', 'Google Inc.');
  mask(navigator, 'productSub', '20030107');
  mask(navigator, 'doNotTrack', null);

  // --- screen & window geometry ----------------------------------------
  const s = P.screen;
  mask(screen, 'width', s.width);
  mask(screen, 'height', s.height);
  mask(screen, 'availWidth', s.availWidth);
  mask(screen, 'availHeight', s.availHeight);
  mask(screen, 'colorDepth', s.colorDepth);
  mask(screen, 'pixelDepth', s.pixelDepth);
  try {
    mask(screen.orientation, 'type', s.orientationType);
    mask(screen.orientation, 'angle', s.orientationAngle);
  } catch (_) {}
  mask(window, 'devicePixelRatio', s.devicePixelRatio);
  mask(window, 'screenX', 0); mask(window, 'screenY', 0);
  mask(window, 'screenLeft', 0); mask(window, 'screenTop', 0);

  // --- plugins & mimeTypes (PDF stack) ---------------------------------
  const makeMime = (type, plugin) => {
    const m = Object.create(MimeType.prototype);
    Object.defineProperties(m, {
      type: { value: type, enumerable: true },
      suffixes: { value: 'pdf', enumerable: true },
      description: { value: 'Portable Document Format', enumerable: true },
      enabledPlugin: { value: plugin, enumerable: true },
    });
    return m;
  };
  const plugins = P.plugins.map((name) => {
    const p = Object.create(Plugin.prototype);
    const a = makeMime('application/pdf', p);
    const b = makeMime('text/pdf', p);
    Object.defineProperties(p, {
      name: { value: name, enumerable: true },
      filename: { value: 'internal-pdf-viewer', enumerable: true },
      description: { value: 'Portable Document Format', enumerable: true },
      length: { value: 2, enumerable: true },
    });
    p[0] = a; p[1] = b; p['application/pdf'] = a; p['text/pdf'] = b;
    p.item = function (i) { return this[i]; };
    p.namedItem = function (n) { return this[n]; };
    return p;
  });
  const pluginArr = Object.create(PluginArray.prototype);
  plugins.forEach((p, i) => { pluginArr[i] = p; pluginArr[p.name] = p; });
  Object.defineProperty(pluginArr, 'length', { value: plugins.length });
  pluginArr.item = function (i) { return this[i]; };
  pluginArr.namedItem = function (n) { return this[n]; };
  pluginArr.refresh = function () {};
  pluginArr[Symbol.iterator] = function* () { for (let i = 0; i < this.length; i++) yield this[i]; };
  mask(navigator, 'plugins', pluginArr);

  const mimeArr = Object.create(MimeTypeArray.prototype);
  const seen = new Set(); let mi = 0;
  plugins.forEach((p) => {
    for (let i = 0; i < p.length; i++) {
      const m = p[i];
      if (seen.has(m.type)) continue;
      seen.add(m.type); mimeArr[mi] = m; mimeArr[m.type] = m; mi++;
    }
  });
  Object.defineProperty(mimeArr, 'length', { value: mi });
  mimeArr.item = function (i) { return this[i]; };
  mimeArr.namedItem = function (n) { return this[n]; };
  mask(navigator, 'mimeTypes', mimeArr);

  // --- permissions & notifications -------------------------------------
  try {
    const realQuery = navigator.permissions.query.bind(navigator.permissions);
    navigator.permissions.query = spoofToString((params) => {
      if (params && params.name === 'notifications') {
        return Promise.resolve({ state: Notification.permission, onchange: null });
      }
      return realQuery(params);
    }, navigator.permissions.query);
  } catch (_) {}

  // --- WebGL vendor / renderer -----------------------------------------
  const gl = P.gpu;
  const patchGL = (proto) => {
    if (!proto || !proto.getParameter) return;
    const real = proto.getParameter;
    proto.getParameter = spoofToString(function (p) {
      if (p === 37445) return gl.vendor;      // UNMASKED_VENDOR_WEBGL
      if (p === 37446) return gl.renderer;    // UNMASKED_RENDERER_WEBGL
      return real.apply(this, arguments);
    }, real);
  };
  patchGL(window.WebGLRenderingContext && WebGLRenderingContext.prototype);
  patchGL(window.WebGL2RenderingContext && WebGL2RenderingContext.prototype);

  // --- battery ----------------------------------------------------------
  const bat = P.battery;
  const batteryObj = {
    charging: bat.charging, level: bat.level,
    chargingTime: bat.chargingTime == null ? Infinity : bat.chargingTime,
    dischargingTime: bat.dischargingTime == null ? Infinity : bat.dischargingTime,
    addEventListener() {}, removeEventListener() {}, dispatchEvent() { return true; },
    onchargingchange: null, onlevelchange: null,
    onchargingtimechange: null, ondischargingtimechange: null,
  };
  if (navigator.getBattery) navigator.getBattery = () => Promise.resolve(batteryObj);

  // --- network information ---------------------------------------------
  if (navigator.connection) {
    const c = P.connection;
    mask(navigator.connection, 'effectiveType', c.effectiveType);
    mask(navigator.connection, 'rtt', c.rtt);
    mask(navigator.connection, 'downlink', c.downlink);
    mask(navigator.connection, 'saveData', c.saveData);
  }

  // --- speech voices ----------------------------------------------------
  if (window.speechSynthesis) {
    const build = () => P.voices.map((v) => {
      const o = Object.create(SpeechSynthesisVoice.prototype);
      Object.defineProperties(o, {
        name: { value: v.name, enumerable: true },
        lang: { value: v.lang, enumerable: true },
        default: { value: !!v.default, enumerable: true },
        localService: { value: !!v.localService, enumerable: true },
        voiceURI: { value: v.voiceURI, enumerable: true },
      });
      return o;
    });
    const real = window.speechSynthesis.getVoices.bind(window.speechSynthesis);
    window.speechSynthesis.getVoices = spoofToString(() => {
      const r = real();
      return r && r.length ? r : build();
    }, window.speechSynthesis.getVoices);
  }

  // --- deterministic-per-site audio noise ------------------------------
  let seed = 0;
  for (const ch of (location.host || 'x')) seed = (seed * 31 + ch.charCodeAt(0)) & 0x7fffffff;
  seed = seed || 1;
  const next = () => { seed = (seed * 1103515245 + 12345) & 0x7fffffff; return seed / 0x7fffffff; };
  const realChannel = AudioBuffer.prototype.getChannelData;
  AudioBuffer.prototype.getChannelData = spoofToString(function () {
    const data = realChannel.apply(this, arguments);
    for (let i = 0; i < data.length; i += 1000) data[i] += (next() - 0.5) * 1e-7;
    return data;
  }, realChannel);

  // --- deterministic-per-site canvas noise -----------------------------
  // Perturb the pixel buffer just before it is read out so the hash is stable
  // per host yet different from a stock browser. getImageData throws on
  // cross-origin tainted canvases, so fall back to the original untouched.
  const origToDataURL = HTMLCanvasElement.prototype.toDataURL;
  HTMLCanvasElement.prototype.toDataURL = spoofToString(function () {
    const ctx = this.getContext('2d');
    if (ctx && this.width > 0 && this.height > 0) {
      try {
        const imageData = ctx.getImageData(0, 0, this.width, this.height);
        for (let i = 0; i < imageData.data.length; i += 4) {
          imageData.data[i]     += (next() - 0.5) * 2;
          imageData.data[i + 1] += (next() - 0.5) * 2;
          imageData.data[i + 2] += (next() - 0.5) * 2;
        }
        ctx.putImageData(imageData, 0, 0);
      } catch (_) {}
    }
    return origToDataURL.apply(this, arguments);
  }, origToDataURL);
  const origToBlob = HTMLCanvasElement.prototype.toBlob;
  HTMLCanvasElement.prototype.toBlob = spoofToString(function () {
    const ctx = this.getContext('2d');
    if (ctx && this.width > 0 && this.height > 0) {
      try {
        const imageData = ctx.getImageData(0, 0, this.width, this.height);
        for (let i = 0; i < imageData.data.length; i += 16) {
          imageData.data[i] ^= 1;
        }
        ctx.putImageData(imageData, 0, 0);
      } catch (_) {}
    }
    return origToBlob.apply(this, arguments);
  }, origToBlob);

  // --- storage quota ----------------------------------------------------
  if (navigator.storage && navigator.storage.estimate) {
    const realEstimate = navigator.storage.estimate.bind(navigator.storage);
    navigator.storage.estimate = spoofToString(async () => {
      const est = await realEstimate();
      est.quota = 299707068416; // ~279 GB, typical desktop free space
      return est;
    }, navigator.storage.estimate);
  }

  // --- media device enumeration ----------------------------------------
  // Return the unprivileged shape: kind preserved, identifiers/label blanked
  // together (Chrome never blanks deviceId while keeping a populated label).
  if (navigator.mediaDevices && navigator.mediaDevices.enumerateDevices) {
    const realEnum = navigator.mediaDevices.enumerateDevices.bind(navigator.mediaDevices);
    navigator.mediaDevices.enumerateDevices = spoofToString(async () => {
      const devices = await realEnum();
      return devices.map((d) => ({
        deviceId: '', kind: d.kind, label: '', groupId: '',
        toJSON() { return { deviceId: '', kind: this.kind, label: '', groupId: '' }; },
      }));
    }, navigator.mediaDevices.enumerateDevices);
  }

  // --- timezone (only when a proxy geo lookup supplied one) ------------
  if (P.timezone) {
    try {
      const realResolved = Intl.DateTimeFormat.prototype.resolvedOptions;
      Intl.DateTimeFormat.prototype.resolvedOptions = spoofToString(function () {
        const r = realResolved.apply(this, arguments);
        r.timeZone = P.timezone;
        return r;
      }, realResolved);
    } catch (_) {}
  }
  if (P.tzOffset != null) {
    try {
      const realOffset = Date.prototype.getTimezoneOffset;
      Date.prototype.getTimezoneOffset = spoofToString(() => P.tzOffset, realOffset);
    } catch (_) {}
  }
})();
"""


def build(fp: Fingerprint) -> str:
    """Serialise a fingerprint into the ready-to-inject init script."""
    return _TEMPLATE.replace("__PROFILE__", json.dumps(fp.as_dict()))
