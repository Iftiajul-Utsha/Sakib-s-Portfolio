import * as THREE from "three";

document.documentElement.classList.add("js");

const SIGNAL_BRIGHT = 0xff1a0d;
const reduceMotion = matchMedia("(prefers-reduced-motion: reduce)").matches;
const $ = (s) => document.querySelector(s);
const $$ = (s) => [...document.querySelectorAll(s)];
const clamp = (v, a, b) => Math.min(b, Math.max(a, v));
const easeOut = (t) => 1 - Math.pow(1 - t, 5);
const CODE_CHARS = "01アイウエオカキクケコサシスセソ{}[]<>/=+*#$&";

/* tiny tween runner (driven by the 3D render loop) */
const tweens = [];
function tween(duration, delay, fn) {
  tweens.push({ start: performance.now() + delay, duration: reduceMotion ? 300 : duration, fn });
}
function runTweens(now) {
  for (let i = tweens.length - 1; i >= 0; i--) {
    const tw = tweens[i];
    const k = clamp((now - tw.start) / tw.duration, 0, 1);
    tw.fn(easeOut(k));
    if (k >= 1) tweens.splice(i, 1);
  }
}

/* ================================================================== */
/* HERO: crisp 2D photo in a 3D space                                  */
/* ================================================================== */
function initHero() {
  // the name decodes out of code, letter by letter, then locks in white
  const el = $("#hero-word");
  if (!el) return;
  const FINAL = "SAKIB";
  const POOL = "ABCDEFGHKMNPRSTUVXYZ0123456789#$";
  if (reduceMotion) return;
  const t0 = performance.now();
  (function step() {
    const locked = Math.floor(clamp((performance.now() - t0 - 300) / 190, 0, FINAL.length));
    el.innerHTML = [...FINAL].map((ch, i) =>
      i < locked ? ch : `<span class="scr">${POOL[(Math.random() * POOL.length) | 0]}</span>`).join("");
    if (locked < FINAL.length) setTimeout(step, 45);
  })();
}

/* ================================================================== */
/* Matrix code rain behind the page                                    */
/* ================================================================== */
function initRain(c = $("#rain"), overlay = false) {
  // overlay = drawn over the hero photo: trails fade to TRANSPARENT instead of painting black
  if (!c) return;
  const ctx = c.getContext("2d");
  const chars = [...CODE_CHARS, ..."ハヒフヘホナニヌネノ"];
  const size = 16;
  let cols = 0, drops = [], w = 0, h = 0;
  const dpr = Math.min(devicePixelRatio, overlay ? 1.5 : 2);
  function resize() {
    w = overlay ? c.clientWidth : innerWidth; h = overlay ? c.clientHeight : innerHeight;
    c.width = w * dpr; c.height = h * dpr;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    cols = Math.ceil(w / size);
    drops = Array.from({ length: cols }, () => Math.random() * (h / size));
    if (!overlay) { ctx.fillStyle = "#1d1a1a"; ctx.fillRect(0, 0, w, h); }
  }
  resize();
  addEventListener("resize", resize);
  function draw() {
    if (overlay) {
      ctx.globalCompositeOperation = "destination-out";       // fade old glyphs to transparent
      ctx.fillStyle = "rgba(0, 0, 0, 0.08)";
      ctx.fillRect(0, 0, w, h);
      ctx.globalCompositeOperation = "source-over";
    } else {
      ctx.fillStyle = "rgba(29, 26, 26, 0.06)";   // trails fade into the charcoal page
      ctx.fillRect(0, 0, w, h);
    }
    ctx.font = `${size}px "JetBrains Mono", Consolas, monospace`;
    for (let i = 0; i < cols; i++) {
      const y = drops[i] * size;
      ctx.fillStyle = Math.random() < 0.04 ? "#ffd9d6" : "#ff1a0d";
      ctx.fillText(chars[(Math.random() * chars.length) | 0], i * size, y);
      if (y > h && Math.random() > 0.975) drops[i] = 0;
      drops[i] += 1;
    }
  }
  if (reduceMotion) { for (let i = 0; i < 60; i++) draw(); return; }
  let last = 0, on = true;
  if (overlay) new IntersectionObserver(([e]) => (on = e.isIntersecting)).observe(c);
  (function frame(now) {
    requestAnimationFrame(frame);
    if (!on || now - last < 50) return;
    last = now;
    draw();
  })(0);
}

/* ================================================================== */
/* Section titles decode like code (once)                              */
/* ================================================================== */
function decode(el) {
  const text = el.textContent;
  el.setAttribute("aria-label", text);
  if (reduceMotion) return;
  const t0 = performance.now();
  (function step() {
    const t = performance.now() - t0;
    let out = "";
    for (let i = 0; i < text.length; i++) {
      if (text[i] === " " || t > 120 + i * 45) out += text[i];
      else out += CODE_CHARS[(Math.random() * CODE_CHARS.length) | 0];
    }
    el.textContent = out;
    if (out !== text) setTimeout(step, 40);
  })();
}

/* ================================================================== */
/* Page chrome: header, progress, active nav, entrances                */
/* ================================================================== */
function initChrome() {
  const header = $("#site-header");
  const bar = $("#progress-bar");
  let ticking = false;
  function onScroll() {
    if (ticking) return;
    ticking = true;
    requestAnimationFrame(() => {
      const max = document.documentElement.scrollHeight - innerHeight;
      bar.style.transform = `scaleX(${max > 0 ? scrollY / max : 0})`;
      header.classList.toggle("solid", scrollY > innerHeight * 0.55);
      ticking = false;
    });
  }
  addEventListener("scroll", onScroll, { passive: true });
  onScroll();

  // highlight the section you're reading
  const links = $$("[data-nav]");
  const navIO = new IntersectionObserver((entries) => {
    entries.forEach((e) => {
      if (!e.isIntersecting) return;
      links.forEach((a) => a.classList.toggle("active", a.dataset.nav === e.target.id));
    });
  }, { rootMargin: "-45% 0px -50% 0px" });
  links.forEach((a) => { const s = document.getElementById(a.dataset.nav); if (s) navIO.observe(s); });

  // one-time entrances: lists cascade, statements wipe in, titles decode
  $$(".stagger").forEach((list) => [...list.children].forEach((li, i) => li.style.setProperty("--i", i)));
  const io = new IntersectionObserver((entries) => {
    entries.forEach((e) => {
      if (!e.isIntersecting) return;
      e.target.classList.add("in");
      if (e.target.matches("[data-decode]")) decode(e.target);
      io.unobserve(e.target);
    });
  }, { threshold: 0.2, rootMargin: "0px 0px -8% 0px" });
  $$(".stagger, .reveal-mask, [data-decode]").forEach((el) => io.observe(el));
}

function initTerminal() {
  const el = $("#typed");
  const caret = $(".caret");
  const line = "while (!top) climb();";
  if (reduceMotion) { el.textContent = line; caret.classList.add("done"); return; }
  let i = 0;
  setTimeout(function type() {
    el.textContent = line.slice(0, ++i);
    if (i < line.length) setTimeout(type, 45 + Math.random() * 40);
    else caret.classList.add("done");
  }, 900);
}

/* ================================================================== */
/* Connect: two hands made of live code characters                     */
/* Hands modelled with metaballs in Blender (tools/build_hands.py),    */
/* sampled into points; every point is drawn as a flickering glyph.    */
/* ================================================================== */
async function initHands() {
  const host = $("#hands");
  const section = $("#connect");
  if (!host) return;
  let renderer;
  try {
    renderer = new THREE.WebGLRenderer({ antialias: false, alpha: true, powerPreference: "high-performance" });
    if (!renderer.getContext()) throw new Error("no gl");
  } catch { return; }
  renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
  renderer.setClearColor(0x000000, 0);
  host.appendChild(renderer.domElement);

  // ---- letter art traced from the hand drawing (tools/hands_from_image.py)
  //      header: uint32 count, f32 lightX, f32 lightY ; point: int16 x,y,z (/3000), uint8 tone, uint8 side<<4|kind
  const buf = await (await fetch("assets/hands_art.bin")).arrayBuffer();
  const dv = new DataView(buf);
  const count = dv.getUint32(0, true);
  const spark = new THREE.Vector3(dv.getFloat32(4, true), dv.getFloat32(8, true), 0.12);
  const pos = new Float32Array(count * 3), start = new Float32Array(count * 3);
  const seed = new Float32Array(count), tone = new Float32Array(count), side = new Float32Array(count), kind = new Float32Array(count);
  for (let i = 0; i < count; i++) {
    const o = 12 + i * 8;
    const x = dv.getInt16(o, true) / 3000, y = dv.getInt16(o + 2, true) / 3000, z = dv.getInt16(o + 4, true) / 3000;
    pos.set([x, y, z], i * 3);
    tone[i] = dv.getUint8(o + 6) / 255;
    const f = dv.getUint8(o + 7);
    side[i] = f >> 4; kind[i] = f & 15; seed[i] = Math.random();
    // letters stream in from the side their arm comes from
    const dir = side[i] < 0.5 ? -1 : 1;
    start.set([x + dir * (3 + Math.random() * 7), y + (Math.random() - 0.5) * 5, z + (Math.random() - 0.5) * 5 - 1], i * 3);
  }

  const geo = new THREE.BufferGeometry();
  geo.setAttribute("position", new THREE.BufferAttribute(pos, 3));
  geo.setAttribute("aStart", new THREE.BufferAttribute(start, 3));
  geo.setAttribute("aSeed", new THREE.BufferAttribute(seed, 1));
  geo.setAttribute("aTone", new THREE.BufferAttribute(tone, 1));
  geo.setAttribute("aKind", new THREE.BufferAttribute(kind, 1));
  geo.setAttribute("aSide", new THREE.BufferAttribute(side, 1));

  // ---- glyph atlas: 0-31 letters (human hand), 32-63 digits + hex (robot hand)
  const GL = "ABCDEFGHJKLMNPQRSTUVWXYZabdefhkm" + "0123456789ABCDEF0101#$%*+=<>[]{}";
  const atlas = document.createElement("canvas");
  atlas.width = atlas.height = 512;
  const actx = atlas.getContext("2d");
  actx.fillStyle = "#fff";
  actx.font = 'bold 50px "JetBrains Mono", Consolas, monospace';
  actx.textAlign = "center"; actx.textBaseline = "middle";
  for (let i = 0; i < 64; i++) actx.fillText(GL[i], (i % 8) * 64 + 32, Math.floor(i / 8) * 64 + 34);
  const atlasTex = new THREE.CanvasTexture(atlas);
  atlasTex.generateMipmaps = false;
  atlasTex.minFilter = THREE.LinearFilter;

  const uniforms = {
    uTime: { value: 0 },
    uAssemble: { value: reduceMotion ? 1 : 0 },
    uScale: { value: 1 },
    uSpark: { value: spark },
    uAtlas: { value: atlasTex },
  };
  const mat = new THREE.ShaderMaterial({
    uniforms,
    transparent: true,
    depthWrite: false,
    blending: THREE.AdditiveBlending,
    vertexShader: /* glsl */ `
      uniform float uTime, uAssemble, uScale;
      uniform vec3 uSpark;
      attribute vec3 aStart;
      attribute float aSeed, aTone, aKind, aSide;
      varying float vGlyph, vHeat, vTone, vAlpha, vRed, vRobot, vKind;
      void main() {
        float d = clamp(uAssemble * 1.5 - aSeed * 0.5, 0.0, 1.0);
        d = 1.0 - pow(1.0 - d, 4.0);
        vec3 p = mix(aStart, position, d);
        p += 0.003 * vec3(sin(uTime * 2.3 + aSeed * 40.0), cos(uTime * 1.9 + aSeed * 31.0), 0.0);
        vec4 mv = modelViewMatrix * vec4(p, 1.0);
        gl_Position = projectionMatrix * mv;
        gl_PointSize = 0.05 * uScale / -mv.z * (0.85 + aSeed * 0.35) * (aKind > 0.5 ? 0.9 : 1.0);
        vRobot = 1.0 - step(0.5, aSide);                                   // left hand = machine
        float speed = vRobot > 0.5 ? 2.5 + aSeed * 8.0 : 0.8 + aSeed * 3.5;  // machine flickers faster
        vGlyph = mod(floor(aSeed * 97.0 + uTime * speed), 32.0) + vRobot * 32.0;
        vKind = aKind;
        vHeat = smoothstep(1.6, 0.0, distance(p.xy, uSpark.xy));
        vTone = aTone;
        vAlpha = d;
        // a few letters flare red now and then
        vRed = step(0.985, fract(aSeed * 13.7 + floor(uTime * 0.7 + aSeed * 5.0) * 0.137));
      }`,
    fragmentShader: /* glsl */ `
      uniform sampler2D uAtlas;
      uniform float uTime;
      varying float vGlyph, vHeat, vTone, vAlpha, vRed, vRobot, vKind;
      void main() {
        vec2 cell = vec2(mod(vGlyph, 8.0), floor(vGlyph / 8.0));
        vec2 uv = vec2((cell.x + gl_PointCoord.x) / 8.0, 1.0 - (cell.y + gl_PointCoord.y) / 8.0);
        float a = texture2D(uAtlas, uv).a;
        if (a < 0.12) discard;
        vec3 col;
        float boost = 0.0;
        if (vRobot > 0.5) {
          if (vKind > 2.5) {                                                 // glowing joints: pulse
            float g = 0.7 + 0.3 * sin(uTime * 3.0 + gl_FragCoord.x * 0.01);
            col = vec3(1.0, 0.42, 0.3) * (0.75 + 0.45 * g);
            boost = 0.3 * g;
          } else if (vKind > 1.5) {                                          // machined edges: chrome highlights
            col = vec3(0.9, 0.94, 1.0) * (0.55 + 0.6 * vTone);
            boost = 0.22;
          } else if (vKind > 0.5) {                                          // silhouette: signal red rim
            col = vec3(1.0, 0.12, 0.06) * 1.2;
            boost = 0.25;
          } else {                                                           // polished steel
            col = vec3(0.8, 0.84, 0.9) * (0.22 + 0.95 * vTone);
          }
        } else {
          col = vec3(0.95, 0.93, 0.9) * (0.18 + 0.82 * vTone);               // human skin
          col = mix(col, vec3(1.0, 0.16, 0.08), vRed * 0.9);                  // occasional red flare
        }
        col = mix(col, vec3(1.0, 0.55, 0.45), vHeat * 0.5);                  // warmed by the light
        float alpha = a * vAlpha * (0.16 + 0.6 * vTone + boost + 0.35 * vHeat + 0.4 * vRed * (1.0 - vRobot));
        gl_FragColor = vec4(col, alpha);
      }`,
  });

  const scene = new THREE.Scene();
  const group = new THREE.Group();
  scene.add(group);
  group.add(new THREE.Points(geo, mat));

  // ---- the light between the fingertips: soft halo + hot core
  const makeGlow = (stops) => {
    const c = document.createElement("canvas");
    c.width = c.height = 256;
    const g = c.getContext("2d");
    const grad = g.createRadialGradient(128, 128, 0, 128, 128, 128);
    stops.forEach(([o, col]) => grad.addColorStop(o, col));
    g.fillStyle = grad; g.fillRect(0, 0, 256, 256);
    return new THREE.CanvasTexture(c);
  };
  const halo = new THREE.Sprite(new THREE.SpriteMaterial({
    map: makeGlow([[0, "rgba(255,170,150,0.7)"], [0.22, "rgba(255,60,35,0.35)"], [0.55, "rgba(200,10,0,0.1)"], [1, "rgba(255,0,0,0)"]]),
    blending: THREE.AdditiveBlending, depthWrite: false, transparent: true, opacity: 0,
  }));
  const core = new THREE.Sprite(new THREE.SpriteMaterial({
    map: makeGlow([[0, "rgba(255,255,255,1)"], [0.18, "rgba(255,225,215,0.85)"], [0.5, "rgba(255,60,40,0.18)"], [1, "rgba(255,0,0,0)"]]),
    blending: THREE.AdditiveBlending, depthWrite: false, transparent: true, opacity: 0,
  }));
  halo.position.copy(spark); core.position.copy(spark);
  group.add(halo, core);

  // ---- embers hugging the light
  const EN = 120;
  const ePos = new Float32Array(EN * 3), ePh = new Float32Array(EN);
  for (let i = 0; i < EN; i++) ePh[i] = Math.random() * Math.PI * 2;
  const eGeo = new THREE.BufferGeometry();
  eGeo.setAttribute("position", new THREE.BufferAttribute(ePos, 3));
  const embers = new THREE.Points(eGeo, new THREE.PointsMaterial({ color: 0xff5a40, size: 0.02, transparent: true, opacity: 0, blending: THREE.AdditiveBlending, depthWrite: false }));
  group.add(embers);

  // ---- depth field: large out-of-focus letters drifting through the space
  const FN = 150;
  const fPos = new Float32Array(FN * 3), fSeed = new Float32Array(FN);
  for (let i = 0; i < FN; i++) {
    fPos.set([(Math.random() - 0.5) * 12, (Math.random() - 0.5) * 6, -4 + Math.random() * 7], i * 3);
    fSeed[i] = Math.random();
  }
  const fGeo = new THREE.BufferGeometry();
  fGeo.setAttribute("position", new THREE.BufferAttribute(fPos, 3));
  fGeo.setAttribute("aSeed", new THREE.BufferAttribute(fSeed, 1));
  const fMat = new THREE.ShaderMaterial({
    uniforms: { uTime: uniforms.uTime, uScale: uniforms.uScale, uAtlas: uniforms.uAtlas, uFade: { value: 0 } },
    transparent: true, depthWrite: false, blending: THREE.AdditiveBlending,
    vertexShader: /* glsl */ `
      uniform float uTime, uScale;
      attribute float aSeed;
      varying float vGlyph, vA, vRed;
      void main() {
        vec3 p = position;
        p.y = mod(p.y + uTime * (0.05 + aSeed * 0.08) + 3.0, 6.0) - 3.0;
        vec4 mv = modelViewMatrix * vec4(p, 1.0);
        gl_Position = projectionMatrix * mv;
        float depth = -mv.z;
        gl_PointSize = (0.15 + aSeed * 0.12) * uScale / depth;
        vGlyph = mod(floor(aSeed * 61.0 + uTime * (0.3 + aSeed)), 64.0);
        vA = (0.16 + 0.2 * aSeed) * smoothstep(7.0, 1.0, abs(depth - 8.5));
        vRed = step(0.7, aSeed);
      }`,
    fragmentShader: /* glsl */ `
      uniform sampler2D uAtlas;
      uniform float uFade;
      varying float vGlyph, vA, vRed;
      void main() {
        vec2 cell = vec2(mod(vGlyph, 8.0), floor(vGlyph / 8.0));
        vec2 uv = vec2((cell.x + gl_PointCoord.x) / 8.0, 1.0 - (cell.y + gl_PointCoord.y) / 8.0);
        float a = texture2D(uAtlas, uv).a;
        vec3 col = mix(vec3(0.75), vec3(1.0, 0.12, 0.06), vRed);
        gl_FragColor = vec4(col, a * vA * uFade);
      }`,
  });
  group.add(new THREE.Points(fGeo, fMat));

  const camera = new THREE.PerspectiveCamera(30, 1, 0.1, 100);
  function layout() {
    const w = host.clientWidth, h = host.clientHeight;
    renderer.setSize(w, h, false);
    camera.aspect = w / h;
    camera.updateProjectionMatrix();
    const wide = w / h > 1;
    const fitW = wide ? 8.6 : 3.9;                              // the art is 9.6 wide: arms run past both edges
    const z = fitW / (2 * Math.tan(THREE.MathUtils.degToRad(15)) * camera.aspect);
    camera.position.set(0, 0, Math.max(z, 5));
    group.position.set(-spark.x, -spark.y + (wide ? 0.2 : 0.15), 0);
    uniforms.uScale.value = (h * renderer.getPixelRatio()) / (2 * Math.tan(THREE.MathUtils.degToRad(15)));
  }
  layout();
  addEventListener("resize", layout);

  const target = { x: 0, y: 0 }, cur = { x: 0, y: 0 };
  addEventListener("pointermove", (e) => {
    if (e.pointerType !== "mouse") return;
    target.x = (e.clientX / innerWidth) * 2 - 1;
    target.y = (e.clientY / innerHeight) * 2 - 1;
  }, { passive: true });

  let visible = false;
  new IntersectionObserver(([e]) => (visible = e.isIntersecting), { rootMargin: "120px" }).observe(host);

  let assembleTarget = reduceMotion ? 1 : 0;
  function measure() {
    const r = section.getBoundingClientRect();
    assembleTarget = reduceMotion ? 1 : clamp((innerHeight - r.top) / (innerHeight * 0.9), 0, 1);
  }
  addEventListener("scroll", measure, { passive: true });
  measure();

  const clock = new THREE.Clock();
  (function loop() {
    requestAnimationFrame(loop);
    if (!visible) return;
    const t = clock.getElapsedTime();
    const amp = reduceMotion ? 0 : 1;
    if (amp) uniforms.uTime.value = t;
    uniforms.uAssemble.value += (assembleTarget - uniforms.uAssemble.value) * 0.05;
    cur.x += (target.x - cur.x) * 0.05;
    cur.y += (target.y - cur.y) * 0.05;
    group.rotation.y = (cur.x * 0.22 + Math.sin(t * 0.2) * 0.04) * amp;
    group.rotation.x = cur.y * 0.1 * amp;

    const k = clamp((uniforms.uAssemble.value - 0.7) / 0.3, 0, 1);
    const pulse = 1 + Math.sin(t * 3.0) * 0.1 * amp;
    halo.material.opacity = k; core.material.opacity = k;
    halo.scale.setScalar((1.3 + k * 2.0) * pulse);
    core.scale.setScalar((0.32 + k * 0.42) * (1 + Math.sin(t * 7.0) * 0.05 * amp));
    embers.material.opacity = k * 0.9;
    fMat.uniforms.uFade.value = clamp(uniforms.uAssemble.value * 1.4, 0, 1);
    for (let i = 0; i < EN; i++) {
      const ph = ePh[i] + t * (0.6 + (i % 7) * 0.15);
      const r = 0.04 + ((i * 37) % 100) / 100 * 0.22;
      ePos[i * 3] = spark.x + Math.cos(ph) * r;
      ePos[i * 3 + 1] = spark.y + Math.sin(ph * 1.3) * r * 0.6;
      ePos[i * 3 + 2] = spark.z + Math.sin(ph) * r * 0.5;
    }
    eGeo.attributes.position.needsUpdate = true;
    renderer.render(scene, camera);
  })();
}

$("#year").textContent = new Date().getFullYear();
initRain();
initRain($("#hero-rain"), true);
initChrome();
initTerminal();
initHero();
initHands();
