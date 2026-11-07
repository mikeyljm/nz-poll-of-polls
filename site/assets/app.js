/* NZ poll of polls — front end. Reads site/data/*.json, written by the pipeline. */
(async function () {
  "use strict";
  const REPO_URL = document.querySelector('meta[name="repo"]')?.content || "";
  const $ = (s) => document.querySelector(s);
  const fmt1 = d3.format(".1f");
  const pct = (v) => (v == null ? "–" : fmt1(v) + "%");
  const signed = (v) => (v == null ? "–" : (v > 0 ? "+" : v < 0 ? "−" : "±") + fmt1(Math.abs(v)));
  const dateFmt = d3.timeFormat("%-d %b %Y");
  const parseDate = d3.timeParse("%Y-%m-%d");
  const tip = $("#tooltip");

  function showTip(html, ev) {
    tip.innerHTML = html;
    tip.hidden = false;
    const pad = 14, w = tip.offsetWidth, h = tip.offsetHeight;
    let x = ev.clientX + pad, y = ev.clientY + pad;
    if (x + w > window.innerWidth - 8) x = ev.clientX - w - pad;
    if (y + h > window.innerHeight - 8) y = ev.clientY - h - pad;
    tip.style.left = x + "px";
    tip.style.top = y + "px";
  }
  const hideTip = () => (tip.hidden = true);
  const range = (a, b) => {
    if (+a === +b) return dateFmt(a);
    if (a.getFullYear() !== b.getFullYear()) return `${dateFmt(a)} – ${dateFmt(b)}`;
    if (a.getMonth() !== b.getMonth()) return `${d3.timeFormat("%-d %b")(a)} – ${dateFmt(b)}`;
    return `${a.getDate()}–${dateFmt(b)}`;
  };

  async function load(name) {
    const r = await fetch("data/" + name, { cache: "no-cache" });
    if (!r.ok) throw new Error(name + " " + r.status);
    return r.json();
  }

  let P, SEATS, LOCS, ELEC, GEO, FINAL;
  try {
    [P, SEATS] = await Promise.all([load("polls.json"), load("seats.json")]);
  } catch (e) {
    $("#updated").textContent = "Couldn't load the data. Please try again shortly.";
    console.error(e);
    return;
  }
  const meta = P.meta;
  const PARTIES = Object.keys(meta.parties);              // includes OTH
  const MAIN = PARTIES.filter((p) => p !== "OTH");
  const name = (p) => meta.parties[p]?.name || p;
  // Brand colours. ACT's yellow is darkened slightly for lines so it holds on white.
  const colour = (p) => (p === "ACT" ? "#E8C800" : meta.parties[p]?.colour || "#999");
  const sw = (p) => `<i class="sw" style="background:${colour(p)}"></i>`;
  if (REPO_URL) $("#repo-link").href = REPO_URL;

  // ------------------------------------------------------------------ header
  const updated = new Date(meta.updated);
  $("#updated").textContent =
    `Updated ${updated.toLocaleString("en-NZ", { dateStyle: "medium", timeStyle: "short", timeZone: "Pacific/Auckland" })} · ` +
    `latest poll ended ${dateFmt(parseDate(meta.last_poll))} · ${meta.polls_this_cycle} poll${meta.polls_this_cycle === 1 ? "" : "s"} since the ${meta.last_election.slice(0, 4)} election`;

  const eYear = meta.last_election.slice(0, 4);
  const banner = [];
  if (meta.polls_this_cycle === 0)
    banner.push(`No polls have been published since the ${eYear} election yet. Until they are, the estimates start from the ${eYear} result and widen week by week; they'll move as polls arrive.`);
  if (meta.last_election_status === "preliminary")
    banner.push(`The ${eYear} result used here is the election-night preliminary count; it will be replaced by the official result.`);
  if (banner.length) {
    $("#banner").innerHTML = banner.map((b) => `<p style="margin:0 0 4px">${b}</p>`).join("");
    $("#banner").hidden = false;
  }

  // ------------------------------------------------------------------ tiles
  const cur = P.current;
  const order = MAIN.slice().sort((a, b) => cur[b].median - cur[a].median);
  $("#vote-sub").textContent =
    `Estimated party vote for the week of ${dateFmt(parseDate(meta.as_of_week))}, with 90% intervals. Change is since the ${eYear} election.`;
  $("#tiles").innerHTML = order
    .map((p) => {
      const c = cur[p];
      return `<div class="tile"><div class="name">${sw(p)}${name(p)}</div>
        <div class="val">${fmt1(c.median)}<small>%</small></div>
        <div class="int">${fmt1(c.lo)}–${fmt1(c.hi)}%</div>
        ${c.since_election != null ? `<div class="delta">${signed(c.since_election)} since ${eYear}</div>` : ""}</div>`;
    })
    .join("");

  // ------------------------------------------------------------------ trend chart
  const weeks = P.weeks.map(parseDate);
  const polls = P.polls.map((d) => ({ ...d, s: parseDate(d.start), e: parseDate(d.end) }))
    .map((d) => ({ ...d, mid: new Date((+d.s + +d.e) / 2) }));
  $("#trend-legend").innerHTML = order.map((p) => `<span><i class="key" style="background:${colour(p)}"></i>${name(p)}</span>`).join("");

  function drawTrend(fromKey) {
    const from = fromKey === "cycle" ? parseDate(meta.last_election) : parseDate(fromKey);
    const el = $("#trend");
    el.innerHTML = "";
    const W = el.clientWidth || 900, H = Math.max(300, Math.min(460, W * 0.5));
    const m = { t: 10, r: 112, b: 28, l: 36 };
    const idx = weeks.map((w, i) => i).filter((i) => weeks[i] >= d3.timeDay.offset(from, -7));
    if (idx.length < 2) idx.unshift(Math.max(0, idx[0] - 1));
    const wk = idx.map((i) => weeks[i]);
    const ps = polls.filter((d) => d.mid >= from);
    const ymax = d3.max(MAIN, (p) => d3.max(idx, (i) => P.trend[p].q95[i])) || 50;
    const pmax = d3.max(ps, (d) => d3.max(MAIN, (p) => d[p] ?? 0)) || 0;
    const x = d3.scaleTime().domain(d3.extent(wk)).range([m.l, W - m.r]);
    const y = d3.scaleLinear().domain([0, Math.ceil(Math.max(ymax, pmax) / 5) * 5]).range([H - m.b, m.t]);
    const svg = d3.select(el).append("svg").attr("viewBox", `0 0 ${W} ${H}`).attr("role", "img")
      .attr("aria-label", "Party vote trend chart");
    svg.append("g").attr("class", "grid").attr("transform", `translate(${m.l},0)`)
      .call(d3.axisLeft(y).ticks(6).tickSize(-(W - m.l - m.r)).tickFormat(""));
    svg.append("g").attr("class", "axis").attr("transform", `translate(0,${H - m.b})`)
      .call(d3.axisBottom(x).ticks(W < 600 ? 4 : 8).tickSizeOuter(0));
    svg.append("g").attr("class", "axis").attr("transform", `translate(${m.l},0)`)
      .call(d3.axisLeft(y).ticks(6).tickFormat((d) => d + "%").tickSize(0)).call((g) => g.select(".domain").remove());

    // elections as vertical markers
    P.elections.forEach((e) => {
      const d = parseDate(e.date);
      if (d < x.domain()[0] || d > x.domain()[1]) return;
      svg.append("line").attr("x1", x(d)).attr("x2", x(d)).attr("y1", m.t).attr("y2", H - m.b)
        .attr("stroke", "var(--rule)").attr("stroke-width", 1);
      svg.append("text").attr("x", x(d) + 4).attr("y", m.t + 10).attr("fill", "var(--muted)")
        .attr("font-size", 11).text(`${e.date.slice(0, 4)} election`);
    });

    const area = (p) => d3.area().x((i) => x(weeks[i])).y0((i) => y(P.trend[p].q05[i])).y1((i) => y(P.trend[p].q95[i]));
    const line = (p) => d3.line().x((i) => x(weeks[i])).y((i) => y(P.trend[p].q50[i]));
    const gP = svg.append("g");
    MAIN.slice().reverse().forEach((p) => {
      gP.append("path").datum(idx).attr("d", area(p)).attr("fill", colour(p)).attr("opacity", 0.12);
    });
    const dotR = ps.length > 150 ? 2.5 : 3.5;
    MAIN.forEach((p) => {
      gP.selectAll(null).data(ps.filter((d) => d[p] != null)).join("circle")
        .attr("cx", (d) => x(d.mid)).attr("cy", (d) => y(d[p])).attr("r", dotR)
        .attr("fill", colour(p)).attr("opacity", 0.38);
    });
    MAIN.forEach((p) => {
      gP.append("path").datum(idx).attr("d", line(p)).attr("fill", "none").attr("stroke", colour(p))
        .attr("stroke-width", 2).attr("stroke-linejoin", "round").attr("stroke-linecap", "round");
    });
    // end labels with leader lines, de-overlapped
    const last = idx[idx.length - 1];
    const labs = MAIN.map((p) => ({ p, y0: y(P.trend[p].q50[last]), v: P.trend[p].q50[last] })).sort((a, b) => a.y0 - b.y0);
    const gap = 14;
    labs.forEach((l, i) => { l.y = i ? Math.max(l.y0, labs[i - 1].y + gap) : l.y0; });
    for (let i = labs.length - 1; i >= 0; i--) if (labs[i].y > H - m.b) labs[i].y = Math.min(labs[i].y, (labs[i + 1]?.y ?? H - m.b + gap) - gap);
    const xe = x(weeks[last]);
    labs.forEach((l) => {
      svg.append("circle").attr("cx", xe).attr("cy", l.y0).attr("r", 4).attr("fill", colour(l.p))
        .attr("stroke", "var(--surface)").attr("stroke-width", 2);
      svg.append("path").attr("d", `M${xe + 5},${l.y0}L${xe + 14},${l.y}`).attr("stroke", "var(--rule)").attr("fill", "none");
      svg.append("text").attr("x", xe + 17).attr("y", l.y + 4).attr("font-size", 12).attr("fill", "var(--ink-2)")
        .text(`${name(l.p).replace("Te Pāti Māori", "TPM")} ${fmt1(l.v)}`);
    });

    // hover layer: crosshair + tooltip
    const cross = svg.append("line").attr("y1", m.t).attr("y2", H - m.b).attr("stroke", "var(--ink-2)")
      .attr("stroke-width", 1).attr("opacity", 0);
    svg.append("rect").attr("x", m.l).attr("y", m.t).attr("width", W - m.l - m.r).attr("height", H - m.t - m.b)
      .attr("fill", "transparent")
      .on("pointermove", (ev) => {
        const [mx] = d3.pointer(ev);
        const t = x.invert(mx);
        const i = idx[Math.max(0, Math.min(idx.length - 1, d3.bisector((j) => weeks[j]).center(idx, t)))];
        cross.attr("x1", x(weeks[i])).attr("x2", x(weeks[i])).attr("opacity", 0.5);
        const rows = MAIN.slice().sort((a, b) => P.trend[b].q50[i] - P.trend[a].q50[i])
          .map((p) => `<tr><td>${sw(p)} ${name(p)}</td><td><b>${fmt1(P.trend[p].q50[i])}</b></td><td class="muted">${fmt1(P.trend[p].q05[i])}–${fmt1(P.trend[p].q95[i])}</td></tr>`).join("");
        const near = ps.filter((d) => Math.abs(d.mid - weeks[i]) < 3.5 * 864e5);
        const pl = near.length ? `<div class="muted" style="margin-top:4px">Polls: ${near.map((d) => meta.pollsters[d.org] || d.org).join(", ")}</div>` : "";
        showTip(`<div class="t-head">Week of ${dateFmt(weeks[i])}</div><table>${rows}</table>${pl}`, ev);
      })
      .on("pointerleave", () => { cross.attr("opacity", 0); hideTip(); });
  }
  let rangeKey = "cycle";
  if (meta.polls_this_cycle < 2) {
    rangeKey = "2023-10-14";
    document.querySelectorAll("#range button").forEach((b) => b.setAttribute("aria-pressed", b.dataset.from === rangeKey));
  }
  document.querySelectorAll("#range button").forEach((b) =>
    b.addEventListener("click", () => {
      document.querySelectorAll("#range button").forEach((x) => x.setAttribute("aria-pressed", x === b));
      rangeKey = b.dataset.from;
      drawTrend(rangeKey);
    }));
  drawTrend(rangeKey);

  // ------------------------------------------------------------------ seats
  const S = SEATS;
  const blocName = (ps) => ps.map(name).join(" + ");
  $("#seats-sub").textContent =
    `From ${d3.format(",")(meta.diagnostics?.draws || 4000)} simulated elections at this week's estimate. A majority is 61 of 120 seats, or more if there's an overhang.`;
  const H = S.headline;
  const hRows = Object.entries(H).map(([k, v]) => {
    const label = k.replace("Right bloc", blocName(S.meta.blocs.right)).replace("Left bloc", blocName(S.meta.blocs.left))
      .replace(S.meta.blocs.kingmaker, name(S.meta.blocs.kingmaker));
    return `<div class="prob-row"><div>${label}</div><div class="bar"><i style="width:${v * 100}%"></i></div><div class="pct">${Math.round(v * 100)}%</div></div>`;
  });
  $("#headline").innerHTML = hRows.join("");
  $("#coalitions").innerHTML = S.coalitions.map((c) =>
    `<div class="prob-row"><div><div class="who">${c.parties.map(sw).join("")}<span>&nbsp;${c.name}</span></div><div class="detail">median ${c.median} seats (${c.lo}–${c.hi})</div></div>
     <div class="bar"><i style="width:${c.p_majority * 100}%"></i></div><div class="pct">${c.p_majority < 0.005 && c.p_majority > 0 ? "<1" : Math.round(c.p_majority * 100)}%</div></div>`).join("");

  (function seatBars() {
    const el = $("#seatbars");
    const ps = Object.keys(S.seats).filter((p) => S.seats[p].hi > 0 && meta.parties[p]).sort((a, b) => S.seats[b].median - S.seats[a].median);
    const W = el.clientWidth || 500, rowH = 34, m = { t: 6, r: 40, b: 24, l: 108 };
    const Hh = m.t + m.b + ps.length * rowH;
    const xmax = Math.ceil(d3.max(ps, (p) => S.seats[p].hi) / 10) * 10;
    const x = d3.scaleLinear().domain([0, xmax]).range([m.l, W - m.r]);
    const svg = d3.select(el).append("svg").attr("viewBox", `0 0 ${W} ${Hh}`).attr("role", "img").attr("aria-label", "Seats by party");
    svg.append("g").attr("class", "grid").attr("transform", `translate(0,${Hh - m.b})`)
      .call(d3.axisBottom(x).ticks(5).tickSize(-(Hh - m.t - m.b)).tickFormat(""));
    svg.append("g").attr("class", "axis").attr("transform", `translate(0,${Hh - m.b})`)
      .call(d3.axisBottom(x).ticks(5).tickSize(0)).call((g) => g.select(".domain").remove());
    ps.forEach((p, i) => {
      const s = S.seats[p], yc = m.t + i * rowH + rowH / 2;
      const g = svg.append("g");
      g.append("text").attr("x", m.l - 10).attr("y", yc + 4).attr("text-anchor", "end").attr("font-size", 13).attr("fill", "var(--ink-2)").text(name(p));
      const bw = Math.max(0, x(s.median) - x(0));
      g.append("path").attr("d", roundedBar(x(0), yc - 8, bw, 16, 4)).attr("fill", colour(p));
      g.append("line").attr("x1", x(s.lo)).attr("x2", x(s.hi)).attr("y1", yc).attr("y2", yc).attr("stroke", "var(--ink)").attr("stroke-width", 1.5);
      [s.lo, s.hi].forEach((v) => g.append("line").attr("x1", x(v)).attr("x2", x(v)).attr("y1", yc - 5).attr("y2", yc + 5).attr("stroke", "var(--ink)").attr("stroke-width", 1.5));
      g.append("text").attr("x", x(Math.max(s.hi, s.median)) + 6).attr("y", yc + 4).attr("font-size", 13).attr("font-weight", 600).attr("fill", "var(--ink)").text(s.median);
      g.append("rect").attr("x", 0).attr("y", yc - rowH / 2).attr("width", W).attr("height", rowH).attr("fill", "transparent")
        .on("pointermove", (ev) => showTip(`<div class="t-head">${sw(p)} ${name(p)}</div>Median ${s.median} seats<br>90% interval ${s.lo}–${s.hi}`, ev))
        .on("pointerleave", hideTip);
    });
  })();

  function roundedBar(x0, y0, w, h, r) {
    r = Math.min(r, w);
    return `M${x0},${y0}H${x0 + w - r}Q${x0 + w},${y0} ${x0 + w},${y0 + r}V${y0 + h - r}Q${x0 + w},${y0 + h} ${x0 + w - r},${y0 + h}H${x0}Z`;
  }

  // electorate assumptions (method section)
  const A = S.electorate_assumptions;
  $("#assumptions").innerHTML = `<div class="table-wrap"><table class="data"><thead><tr><th class="l">Electorate</th><th class="l">Assumed chance of winning (at each party's current median)</th></tr></thead><tbody>${
    Object.entries(A.probabilities).map(([e, pr]) => `<tr><td>${e}</td><td class="l">${Object.entries(pr).map(([p, v]) => `${sw(p)} ${name(p)} ${Math.round(v * 100)}%`).join(" &nbsp; ")}</td></tr>`).join("")
  }</tbody></table></div>`;

  // ------------------------------------------------------------------ house effects
  (function house() {
    const rows = P.house.filter((r) => r.n_recent > 0).sort((a, b) => b.n_current - a.n_current || b.n_recent - a.n_recent);
    const div = d3.scaleDiverging([-4, 0, 4], (t) => d3.interpolatePuOr(1 - t)).clamp(true);
    const cell = (e) => {
      const bg = d3.color(div(e.mean)); bg.opacity = 0.45;
      return `<td class="cell"><span class="he" style="background:${bg}" title="90% interval ${signed(e.lo)} to ${signed(e.hi)}">${signed(e.mean)}</span></td>`;
    };
    $("#house").innerHTML = `<table class="data"><thead><tr><th class="l">Pollster</th><th>Polls this term</th><th>Since ${P.meta.previous_election.slice(0, 4)}</th>${MAIN.map((p) => `<th>${sw(p)} ${p === "TPM" ? "TPM" : name(p)}</th>`).join("")}</tr></thead><tbody>${
      rows.map((r) => `<tr><td>${r.name}</td><td>${r.n_current}</td><td>${r.n_recent}</td>${MAIN.map((p) => cell(r.effects[p])).join("")}</tr>`).join("")
    }</tbody></table><p class="note">Hover a value for its 90% interval. Only pollsters active since the ${P.meta.previous_election.slice(0, 4)} election are shown.</p>`;
  })();

  // ------------------------------------------------------------------ polls table
  (function pollTable() {
    let rows = polls.filter((d) => d.cycle_current);
    let note = `All ${rows.length} polls since the ${eYear} election, newest first.`;
    if (!rows.length) {
      rows = polls.filter((d) => d.e <= parseDate(meta.last_election)).slice(-15);
      note = `No polls yet this term. The last 15 polls before the ${eYear} election are shown.`;
    }
    rows = rows.slice().sort((a, b) => b.e - a.e);
    $("#polls-sub").textContent = note;
    const LIMIT = 20, all = rows;
    const render = (n) => {
    rows = all.slice(0, n);
    $("#polltable").innerHTML = `<table class="data"><thead><tr><th class="l">Fieldwork</th><th class="l">Pollster</th><th>Sample</th>${MAIN.map((p) => `<th>${sw(p)} ${p === "TPM" ? "TPM" : name(p)}</th>`).join("")}</tr></thead><tbody>${
      rows.map((d) => `<tr><td>${range(d.s, d.e)}</td><td class="l">${meta.pollsters[d.org] || d.org}</td><td>${d.n ? d3.format(",")(d.n) : "–"}</td>${MAIN.map((p) => `<td>${d[p] != null ? fmt1(d[p]) : "–"}</td>`).join("")}</tr>`).join("")
    }</tbody></table>${all.length > n ? `<p><button class="more" id="more-polls">Show all ${all.length} polls</button></p>` : ""}`;
    $("#more-polls")?.addEventListener("click", () => render(all.length));
    };
    render(LIMIT);
  })();

  // ------------------------------------------------------------------ final 2026 check
  try {
    FINAL = await load("final_check.json");
    if (FINAL.parties.some((d) => d.result != null)) drawFinal();
  } catch (e) { /* not yet */ }

  function drawFinal() {
    $("#final-check").hidden = false;
    const ps = FINAL.parties.filter((d) => d.party !== "OTH" && d.result != null).sort((a, b) => b.result - a.result);
    const inside = ps.filter((d) => d.inside_90).length;
    $("#final-sub").textContent = `The model's projection using polls up to ${dateFmt(parseDate(FINAL.projection_date))}, against the ${FINAL.result_status} result. ${inside} of ${ps.length} parties landed inside the 90% interval.`;
    const el = $("#final"), W = el.clientWidth || 700, rowH = 30, m = { t: 8, r: 20, b: 26, l: 110 };
    const Hh = m.t + m.b + ps.length * rowH;
    const x = d3.scaleLinear().domain([0, Math.ceil(d3.max(ps, (d) => Math.max(d.hi, d.result)) / 5) * 5]).range([m.l, W - m.r]);
    const svg = d3.select(el).append("svg").attr("viewBox", `0 0 ${W} ${Hh}`);
    svg.append("g").attr("class", "grid").attr("transform", `translate(0,${Hh - m.b})`).call(d3.axisBottom(x).ticks(6).tickSize(-(Hh - m.t - m.b)).tickFormat(""));
    svg.append("g").attr("class", "axis").attr("transform", `translate(0,${Hh - m.b})`).call(d3.axisBottom(x).ticks(6).tickFormat((d) => d + "%").tickSize(0)).call((g) => g.select(".domain").remove());
    ps.forEach((d, i) => {
      const yc = m.t + i * rowH + rowH / 2;
      svg.append("text").attr("x", m.l - 10).attr("y", yc + 4).attr("text-anchor", "end").attr("font-size", 13).attr("fill", "var(--ink-2)").text(name(d.party));
      svg.append("line").attr("x1", x(d.lo)).attr("x2", x(d.hi)).attr("y1", yc).attr("y2", yc).attr("stroke", colour(d.party)).attr("stroke-width", 6).attr("stroke-linecap", "round").attr("opacity", 0.35);
      svg.append("circle").attr("cx", x(d.median)).attr("cy", yc).attr("r", 4).attr("fill", colour(d.party));
      svg.append("path").attr("d", d3.symbol(d3.symbolDiamond, 70)()).attr("transform", `translate(${x(d.result)},${yc})`).attr("fill", "var(--ink)").attr("stroke", "var(--surface)").attr("stroke-width", 2);
      svg.append("rect").attr("x", 0).attr("y", yc - rowH / 2).attr("width", W).attr("height", rowH).attr("fill", "transparent")
        .on("pointermove", (ev) => showTip(`<div class="t-head">${name(d.party)}</div>Projection ${fmt1(d.median)}% (${fmt1(d.lo)}–${fmt1(d.hi)})<br>Result ${d.result}%`, ev)).on("pointerleave", hideTip);
    });
    d3.select(el).append("div").attr("class", "legend").html(`<span><i class="sw" style="background:var(--ink-2)"></i>Projection (median, 90% interval)</span><span>◆ Result</span>`);
  }

  // ------------------------------------------------------------------ voting places
  try {
    [LOCS, ELEC, GEO] = await Promise.all([load("localities.json"), load("electorates.json"), load("electorates.geojson")]);
  } catch (e) {
    console.error(e);
    return;
  }
  const LP = ["NAT", "LAB", "GRN", "ACT", "NZF", "OPP", "TPM"];
  $("#lean-party").innerHTML = LP.map((p) => `<option value="${p}">${name(p)}</option>`).join("");
  const map = L.map("map", { preferCanvas: true, scrollWheelZoom: false, minZoom: 5 }).setView([-41.0, 173.5], 5.4);
  L.tileLayer("https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png", {
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> &copy; <a href="https://carto.com/attributions">CARTO</a>',
    subdomains: "abcd", maxZoom: 16,
  }).addTo(map);
  map.on("focus", () => map.scrollWheelZoom.enable());
  map.on("blur", () => map.scrollWheelZoom.disable());
  const seatLayer = L.geoJSON(GEO, {
    style: { color: "#55555f", weight: 1, opacity: 0.55, fill: true, fillOpacity: 0 },
    onEachFeature: (f, l) => l.bindTooltip(f.properties.seat, { sticky: true, direction: "top", opacity: 0.9 }),
  }).addTo(map);
  $("#show-seats").addEventListener("change", (e) => (e.target.checked ? seatLayer.addTo(map) : map.removeLayer(seatLayer)));

  const lastYear = LOCS.meta.elections[LOCS.meta.elections.length - 1];
  const leanOf = (l, p, m) => {
    if (m === "latest") { const i = l.years.indexOf(lastYear); return i < 0 ? null : l.lean[p][i]; }
    return l[m]?.[p] ?? null;
  };
  const votesOf = (l) => l.votes[l.votes.length - 1];
  let markers = [];
  let selected = null;
  const rScale = d3.scaleSqrt().domain([0, d3.max(LOCS.localities, votesOf)]).range([2, 16]);

  function drawPlaces() {
    const p = $("#lean-party").value, m = $("#lean-measure").value;
    const vals = LOCS.localities.map((l) => leanOf(l, p, m)).filter((v) => v != null).map(Math.abs);
    const M = Math.max(2, Math.ceil(d3.quantile(vals.sort(d3.ascending), 0.95)));
    const c = d3.scaleDiverging([-M, 0, M], (t) => d3.interpolatePuOr(1 - t)).clamp(true);
    markers.forEach((mk) => map.removeLayer(mk));
    markers = [];
    const list = LOCS.localities.filter((l) => leanOf(l, p, m) != null && l.years.includes(lastYear))
      .sort((a, b) => votesOf(b) - votesOf(a));
    list.forEach((l) => {
      const v = leanOf(l, p, m);
      const mk = L.circleMarker([l.lat, l.lon], {
        radius: rScale(votesOf(l)), color: getComputedStyle(document.body).getPropertyValue("--surface") || "#fff",
        weight: 1, fillColor: c(v), fillOpacity: 0.9,
      }).addTo(map);
      mk.bindTooltip(`<b>${l.name}</b><br>${signed(v)} ${name(p)}`, { direction: "top", opacity: 0.95 });
      mk.on("click", () => { selected = l; placePanel(); });
      markers.push(mk);
    });
    const label = { latest: `${lastYear} election`, recent: "average of the last three elections", trend: `trend extended to ${LOCS.meta.base_year + 3}` }[m];
    const stops = d3.range(0, 1.0001, 0.1).map((t) => c(-M + 2 * M * t));
    $("#map-legend").innerHTML = `<span class="scale">Less ${name(p)} than NZ <i class="ramp" style="background:linear-gradient(90deg,${stops.join(",")})"></i> More ${name(p)} than NZ</span><span class="muted">±${M} points · ${label} · ${list.length} places</span>`;
    if (selected) placePanel();
  }
  $("#lean-party").addEventListener("change", drawPlaces);
  $("#lean-measure").addEventListener("change", drawPlaces);

  function placePanel() {
    const l = selected, p = $("#lean-party").value;
    const panel = $("#place-panel");
    const nat = LOCS.meta.national;
    const rows = l.years.map((y, i) => `<tr><td>${y}</td><td>${pct(l.share[p][i])}</td><td>${pct(nat[y][p])}</td><td><b>${signed(l.lean[p][i])}</b></td><td>${d3.format(",")(l.votes[i])}</td></tr>`).join("");
    panel.innerHTML = `<h4>${l.name}</h4><div class="muted">${l.seat} electorate (2026 boundaries)${l.approx ? " · location approximate" : ""}</div>
      <div id="place-chart" class="chart" style="margin-top:10px"></div>
      <table class="data"><thead><tr><th class="l">Election</th><th>${p === "TPM" ? "TPM" : name(p)}</th><th>NZ</th><th>Lean</th><th>Votes</th></tr></thead><tbody>${rows}</tbody></table>
      <p style="margin:10px 0 0">Recent lean <b>${signed(l.recent?.[p])}</b> · trend to ${LOCS.meta.base_year + 3} <b>${signed(l.trend?.[p])}</b></p>
      ${l.booths.length ? `<p class="muted" style="margin:10px 0 0">Voting places in ${l.years[l.years.length - 1]}:</p><ul>${l.booths.map((b) => `<li>${b}</li>`).join("")}</ul>` : ""}`;
    // mini lean chart
    const el = $("#place-chart"), W = el.clientWidth || 280, Hh = 130, m = { t: 8, r: 8, b: 20, l: 30 };
    const ys = l.lean[p].filter((v) => v != null);
    const ext = Math.max(5, Math.ceil(d3.max(ys.map(Math.abs)) / 5) * 5);
    const x = d3.scaleLinear().domain([2002, Math.max(lastYear, 2023)]).range([m.l, W - m.r]);
    const y = d3.scaleLinear().domain([-ext, ext]).range([Hh - m.b, m.t]);
    const svg = d3.select(el).append("svg").attr("viewBox", `0 0 ${W} ${Hh}`);
    svg.append("g").attr("class", "grid").attr("transform", `translate(${m.l},0)`).call(d3.axisLeft(y).ticks(4).tickSize(-(W - m.l - m.r)).tickFormat(""));
    svg.append("g").attr("class", "axis").attr("transform", `translate(${m.l},0)`).call(d3.axisLeft(y).ticks(4).tickFormat((d) => (d > 0 ? "+" : "") + d).tickSize(0)).call((g) => g.select(".domain").remove());
    svg.append("g").attr("class", "axis").attr("transform", `translate(0,${Hh - m.b})`).call(d3.axisBottom(x).tickValues(LOCS.meta.elections.filter((v, i) => i % 2 === 0 || W > 320)).tickFormat(d3.format("d")).tickSize(0)).call((g) => g.select(".domain").remove());
    svg.append("line").attr("x1", m.l).attr("x2", W - m.r).attr("y1", y(0)).attr("y2", y(0)).attr("stroke", "var(--ink-2)").attr("stroke-width", 1);
    const pts = l.years.map((yr, i) => [yr, l.lean[p][i]]).filter((d) => d[1] != null);
    svg.append("path").datum(pts).attr("d", d3.line().x((d) => x(d[0])).y((d) => y(d[1]))).attr("fill", "none").attr("stroke", colour(p)).attr("stroke-width", 2);
    svg.selectAll(null).data(pts).join("circle").attr("cx", (d) => x(d[0])).attr("cy", (d) => y(d[1])).attr("r", 4).attr("fill", colour(p)).attr("stroke", "var(--surface)").attr("stroke-width", 2);
  }
  drawPlaces();

  // ------------------------------------------------------------------ electorates
  (function electorates() {
    const sc = ELEC.scenario;
    $("#elec-sub").innerHTML = `Projected winners in the 64 general electorates (2026 boundaries), if each voting place keeps its lean and the national vote is today's poll-of-polls median: ${
      ["NAT", "LAB", "GRN", "ACT", "NZF", "OPP"].map((p) => `${name(p)} ${fmt1(sc[p])}%`).join(", ")}. Candidates are assumed to be those who stood in ${ELEC.base_year}. Māori electorates aren't modelled here.`;
    const draw = () => {
      const m = $("#elec-method").value, q = $("#elec-search").value.trim().toLowerCase();
      const cnt = ELEC.counts[m];
      $("#elec-counts").innerHTML = Object.entries(cnt).filter(([, v]) => v > 0).sort((a, b) => b[1] - a[1])
        .map(([p, v]) => `<div class="tile"><div class="name">${sw(p)}${name(p)}</div><div class="val">${v}</div></div>`).join("");
      const rows = ELEC.seats.filter((s) => !q || s.seat.toLowerCase().includes(q)).map((s) => ({ ...s, r: s[m] }))
        .sort((a, b) => a.r.margin - b.r.margin);
      $("#electable").innerHTML = `<table class="data"><thead><tr><th class="l">Electorate</th><th class="l">Projected winner</th><th>Margin</th>${
        ["NAT", "LAB", "GRN", "ACT"].map((p) => `<th>${sw(p)} ${name(p)} cand.</th>`).join("")}<th>National party vote</th><th>Labour party vote</th></tr></thead><tbody>${
        rows.map((s) => `<tr title="Assumed candidates: ${tidy(s.assumed.NAT)} (National), ${tidy(s.assumed.LAB)} (Labour)"><td>${s.seat}</td><td class="l">${sw(s.r.winner)} ${name(s.r.winner)}${s.r.margin < 3 ? ' <span class="muted">(close)</span>' : ""}</td><td>${fmt1(s.r.margin)}</td>${
          ["NAT", "LAB", "GRN", "ACT"].map((p) => `<td>${pct(s.r.candidate[p])}</td>`).join("")}<td>${pct(s.r.party.NAT)}</td><td>${pct(s.r.party.LAB)}</td></tr>`).join("")
      }</tbody></table><p class="note">Sorted from closest to safest. "Close" means a margin under 3 points on the candidate vote. Hover a row to see the assumed candidates.</p>`;
    };
    const tidy = (n) => { if (!n) return "–"; const [s, g] = n.split(","); if (!g) return n; const first = g.trim().split(" ")[0]; return `${first} ${s.charAt(0) + s.slice(1).toLowerCase()}`; };
    $("#elec-method").addEventListener("change", draw);
    $("#elec-search").addEventListener("input", draw);
    draw();
  })();

  // redraw trend on resize
  let rt;
  window.addEventListener("resize", () => { clearTimeout(rt); rt = setTimeout(() => drawTrend(rangeKey), 200); });
})();
