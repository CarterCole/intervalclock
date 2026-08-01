// Spinning phase dial: one revolution per period, sweeping at ω = 2π/P rad/s.
// The circle is the period; the m states are sectors; the gradient sweep is
// the phasor, its trail fading behind the leading edge.

export function makeDial(container, m, { size = 190 } = {}) {
  container.classList.add("dialwrap");
  container.innerHTML = "";
  const dial = document.createElement("div");
  dial.className = "dial";
  dial.style.width = dial.style.height = `${size}px`;

  const sectors = document.createElement("div");
  sectors.className = "sectors";
  const sweep = document.createElement("div");
  sweep.className = "sweep";
  const hub = document.createElement("div");
  hub.className = "hub";
  const stateEl = document.createElement("div");
  stateEl.className = "state";
  const ofEl = document.createElement("div");
  ofEl.className = "of";
  hub.append(stateEl, ofEl);
  dial.append(sectors, sweep, hub);
  container.append(dial);

  const labels = [];
  const d = { dial, sectors, sweep, stateEl, ofEl, labels, m: 0, active: -1, size };
  setModulus(d, m);
  return d;
}

export function setModulus(d, m) {
  if (d.m === m) return;
  d.m = m;
  d.active = -1;
  d.ofEl.textContent = `of ${m}`;
  for (const l of d.labels) l.remove();
  d.labels.length = 0;
  if (m <= 12) {
    const r = d.size * 0.40;
    for (let i = 0; i < m; i++) {
      const mid = ((i + 0.5) / m) * 2 * Math.PI;
      const l = document.createElement("div");
      l.className = "seclabel";
      l.textContent = i;
      l.style.left = `${d.size / 2 + r * Math.sin(mid)}px`;
      l.style.top = `${d.size / 2 - r * Math.cos(mid)}px`;
      d.dial.append(l);
      d.labels.push(l);
    }
  }
  paintSectors(d);
}

function paintSectors(d) {
  const stops = [];
  for (let i = 0; i < d.m; i++) {
    const a0 = (i / d.m) * 360;
    const a1 = ((i + 1) / d.m) * 360;
    const on = i === d.active;
    const col = on
      ? "color-mix(in srgb, var(--accent) 38%, transparent)"
      : i % 2
        ? "color-mix(in srgb, var(--muted) 14%, transparent)"
        : "color-mix(in srgb, var(--muted) 7%, transparent)";
    stops.push(`${col} ${a0}deg ${a1}deg`);
  }
  d.sectors.style.background = `conic-gradient(${stops.join(",")})`;
}

// Arc dial: for composite classes (PSets / arbitrary Φ) — the circle is the
// period with the set's arcs painted on; the hub reads ●/○ for in/out.
export function makeArcDial(container, arcDegs, { size = 150 } = {}) {
  container.classList.add("dialwrap");
  container.innerHTML = "";
  const dial = document.createElement("div");
  dial.className = "dial";
  dial.style.width = dial.style.height = `${size}px`;
  const sectors = document.createElement("div");
  sectors.className = "sectors";
  const sweep = document.createElement("div");
  sweep.className = "sweep";
  const hub = document.createElement("div");
  hub.className = "hub";
  const stateEl = document.createElement("div");
  stateEl.className = "state";
  const ofEl = document.createElement("div");
  ofEl.className = "of";
  ofEl.textContent = "in set";
  hub.append(stateEl, ofEl);
  dial.append(sectors, sweep, hub);
  container.append(dial);
  const on = "color-mix(in srgb, var(--accent) 38%, transparent)";
  const off = "color-mix(in srgb, var(--muted) 7%, transparent)";
  const segs = [];
  for (const [a0, a1] of arcDegs) {
    if (a1 <= 360) segs.push([a0, a1]);
    else { segs.push([a0, 360]); segs.push([0, a1 - 360]); }
  }
  segs.sort((x, y) => x[0] - y[0]);
  const stops = [];
  let cur = 0;
  for (const [a0, a1] of segs) {
    if (a0 > cur) stops.push(`${off} ${cur}deg ${a0}deg`);
    stops.push(`${on} ${Math.max(a0, cur)}deg ${a1}deg`);
    cur = Math.max(cur, a1);
  }
  if (cur < 360) stops.push(`${off} ${cur}deg 360deg`);
  sectors.style.background = `conic-gradient(${stops.join(",")})`;
  return { sweep, stateEl };
}

export function updateArcDial(d, frac, inside) {
  d.sweep.style.transform = `rotate(${frac * 360}deg)`;
  d.stateEl.textContent = inside ? "●" : "○";
  d.stateEl.style.color = inside ? "var(--accent)" : "var(--muted)";
}

// frac: elapsed fraction of the period [0, 1). states: current state(s).
export function updateDial(d, frac, states) {
  d.sweep.style.transform = `rotate(${frac * 360}deg)`;
  const active = states[0] ?? -1;
  if (active !== d.active) {
    d.active = active;
    paintSectors(d);
    d.labels.forEach((l, i) => l.classList.toggle("on", states.includes(i)));
  }
  d.stateEl.textContent = states.join("·");
}
