// Optional extras. The site works without this file (the toggle and highlights need it).
(() => {
  const root = document.documentElement;
  const narrow = matchMedia("(max-width: 64rem)");
  const calm = matchMedia("(prefers-reduced-motion: reduce)");

  // 1. light/dark toggle (the choice is kept in this browser only)
  const btn = document.querySelector(".theme");
  if (btn) {
    const set = (t, save) => {
      root.dataset.theme = t;
      const hint = document.querySelector('meta[name="color-scheme"]');
      if (hint) hint.content = t;
      btn.setAttribute("aria-pressed", String(t === "dark"));
      if (save) { try { localStorage.setItem("theme", t); } catch (e) {} }
    };
    set(root.dataset.theme === "light" ? "light" : "dark", false);
    btn.addEventListener("click", () => set(root.dataset.theme === "light" ? "dark" : "light", true));
  }

  // 2. floating lists: scroll gently, then spring back to rest a moment after you stop.
  //    Wheel events the list can't use any more go straight to the page, so nothing sticks.
  document.querySelectorAll(".side").forEach((side) => {
    const track = side.querySelector(".track");
    if (!track) return;
    let timer = 0, raf = 0, lastSet = -99, goal = 0, lastWheel = 0;

    const rest = () => {
      const H = side.clientHeight;
      const pad = parseFloat(getComputedStyle(track).paddingTop) || 0;
      const L = track.offsetHeight - 2 * pad;
      const top = Math.max(0.12 * H, (H - L) / 2);
      return Math.max(0, Math.min(side.scrollHeight - H, pad - top));
    };
    const setTop = (v) => { lastSet = v; side.scrollTop = v; };
    const cancelSpring = () => { cancelAnimationFrame(raf); raf = 0; };
    const arm = () => { clearTimeout(timer); timer = setTimeout(springBack, 650); };

    function springBack() {
      if (narrow.matches || calm.matches) return;
      const target = rest();
      let pos = side.scrollTop, v = 0, last = performance.now();
      const step = (t) => {
        const dt = Math.min(0.032, (t - last) / 1000);
        last = t;
        v += (-90 * (pos - target) - 11 * v) * dt;   // damped spring, slight overshoot
        pos += v * dt;
        setTop(pos);
        if (Math.abs(pos - target) < 0.4 && Math.abs(v) < 3) { setTop(target); raf = 0; return; }
        raf = requestAnimationFrame(step);
      };
      cancelSpring();
      raf = requestAnimationFrame(step);
    }

    side.addEventListener("wheel", (e) => {
      if (narrow.matches || e.ctrlKey || !e.deltaY) return;
      e.preventDefault();
      cancelSpring();
      const unit = e.deltaMode === 1 ? 16 : e.deltaMode === 2 ? innerHeight : 1;
      const dy = e.deltaY * unit;
      const max = side.scrollHeight - side.clientHeight;
      const now = performance.now();
      if (now - lastWheel > 250) goal = side.scrollTop;
      lastWheel = now;
      if ((dy < 0 && goal <= 0.5) || (dy > 0 && goal >= max - 0.5)) {
        scrollBy({ top: dy, behavior: "instant" });   // list is at its end: the page takes it
      } else {
        goal = Math.max(0, Math.min(max, goal + dy * 0.45));
        side.scrollTo({ top: goal, behavior: Math.abs(dy) < 40 ? "instant" : "smooth" });
      }
      arm();
    }, { passive: false });

    side.addEventListener("scroll", () => {
      if (narrow.matches || Math.abs(side.scrollTop - lastSet) < 1.5) return;
      arm();
    });
    ["pointerdown", "touchstart", "keydown"].forEach((ev) =>
      side.addEventListener(ev, () => { cancelSpring(); clearTimeout(timer); }, { passive: true }));

    const settle = () => { if (!narrow.matches) setTop(rest()); };
    settle();
    addEventListener("load", settle);
    addEventListener("resize", settle);
  });

  // 3. highlight the section you are reading in the left list
  const links = [...document.querySelectorAll(".sections a")];
  const targets = links.map((a) => document.getElementById(decodeURIComponent(a.hash.slice(1))));
  let queued = false;
  const spy = () => {
    queued = false;
    if (!links.length) return;
    const bar = document.querySelector(".bar");
    const top = bar ? bar.offsetHeight : 0;
    const line = top + (innerHeight - top) * 0.3;
    let cur = 0;
    targets.forEach((t, i) => { if (t && t.getBoundingClientRect().top <= line) cur = i; });
    const el = document.documentElement;
    if (el.scrollHeight > innerHeight + 8 && innerHeight + scrollY >= el.scrollHeight - 4) cur = links.length - 1;
    links.forEach((a, i) => {
      if (i === cur) a.setAttribute("aria-current", "location");
      else a.removeAttribute("aria-current");
    });
  };
  const queue = () => { if (!queued) { queued = true; requestAnimationFrame(spy); } };
  addEventListener("scroll", queue, { passive: true });
  addEventListener("resize", queue);
  addEventListener("load", queue);
  document.addEventListener("toggle", queue, true);   // opening or closing a section moves things
  spy();

  // 4. jumping to a collapsed section from the left list opens it
  const openFor = (id) => {
    let el = id && document.getElementById(decodeURIComponent(id));
    for (; el; el = el.parentElement) if (el.tagName === "DETAILS") el.open = true;
  };
  links.forEach((a) => a.addEventListener("click", () => openFor(a.hash.slice(1))));
  addEventListener("hashchange", () => openFor(location.hash.slice(1)));
  openFor(location.hash.slice(1));

  // 5. fade the page out before moving to another page of this site (the fade-in is CSS)
  if (!calm.matches) {
    document.addEventListener("click", (e) => {
      const a = e.target.closest && e.target.closest("a[href]");
      if (!a || e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
      if ((a.target && a.target !== "_self") || a.hasAttribute("download")) return;
      const url = new URL(a.href, location.href);
      if (url.protocol !== location.protocol || url.host !== location.host) return;
      const norm = (p) => p.replace(/index\.html?$/, "").replace(/\.html?$/, "").replace(/\/$/, "") || "/";
      const isPage = /\.html?$/.test(url.pathname) || !/\.[a-z0-9]+$/i.test(url.pathname);
      if (!isPage || norm(url.pathname) === norm(location.pathname)) return;
      e.preventDefault();
      root.classList.add("leaving");
      setTimeout(() => { location.href = a.href; }, 160);
    });
    addEventListener("pageshow", (e) => { if (e.persisted) root.classList.remove("leaving"); });
  }
})();
