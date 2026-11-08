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
  let ELEC_PRE = null;
  try {
    [P, SEATS] = await Promise.all([load("polls.json"), load("seats.json")]);
    ELEC_PRE = await load("electorates.json").catch(() => null);
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
  const nzTime = updated.toLocaleString("en-NZ", { dateStyle: "long", timeStyle: "short", timeZone: "Pacific/Auckland" });
  const np = meta.polls_this_cycle;
  $("#updated").textContent =
    `Updated ${nzTime}. ${np ? `${np} poll${np === 1 ? "" : "s"} since the ${meta.last_election.slice(0, 4)} election, the latest ending ${dateFmt(parseDate(meta.last_poll))}.` : `No polls since the ${meta.last_election.slice(0, 4)} election yet.`}`;

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
    `Estimated support for the week of ${dateFmt(parseDate(meta.as_of_week))}, with change since the ${eYear} election.`;
  (function voteList() {
    const xmax = Math.ceil(d3.max(order, (p) => cur[p].hi) / 10) * 10;
    const xp = (v) => `${(v / xmax) * 100}%`;
    $("#tiles").innerHTML = order.map((p) => {
      const c = cur[p];
      return `<div class="vrow"><div class="pname">${sw(p)}${name(p)}</div>
        <div class="track" aria-hidden="true"><span class="thr" style="left:${xp(5)}"></span>
          <span class="band" style="left:${xp(c.lo)};width:calc(${xp(c.hi)} - ${xp(c.lo)});background:${colour(p)}"></span>
          <span class="mid" style="left:${xp(c.median)};background:${colour(p)}"></span></div>
        <div class="pv">${fmt1(c.median)}%</div>
        <div class="pi">${fmt1(c.lo)}–${fmt1(c.hi)}${c.since_election != null ? `<br>${signed(c.since_election)} since ${eYear}` : ""}</div></div>`;
    }).join("") + `<p class="note" style="margin-top:8px">Bars show the 90% interval; the dashed line is the 5% threshold.</p>`;
  })();

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
    `From ${d3.format(",")(meta.diagnostics?.draws || 5000)} simulated elections at this week's estimate. A majority is 61 of 120 seats, or more if there's an overhang.${S.meta.total_seats.p_overhang > 0.05 && S.meta.total_seats.p_overhang <= 0.5 ? ` Parliament has an overhang in ${Math.round(S.meta.total_seats.p_overhang * 100)}% of simulations.` : ""}`;
  if (S.meta.total_seats.p_overhang > 0.5 && S.seats.NAT && S.seats.NAT.median > 0) {
    const nE = ELEC_PRE?.sim_counts?.recent?.NAT?.median;
    $("#overhang-note").innerHTML = `<b>Why Parliament has more than 120 seats.</b> National and Labour are close on the party vote, but National is projected to win${nE ? ` about ${nE}` : " more"} of the 64 general electorates, partly because most ACT and NZ First voters give their electorate vote to the National candidate. When a party wins more electorates than its party vote entitles it to, it keeps them and Parliament grows (an overhang), which raises the bar for a majority. No major party has had an overhang before, and this depends on candidates and vote-splitting staying as they were; see <a href="#electorates">Electorates</a>.`;
    $("#overhang-note").hidden = false;
  }
  // ------------------------------------------------------------------ hero: answer + the House
  (function hero() {
    const H0 = S.headline, b = S.meta.blocs;
    const pc = (v) => (v > 0 && v < 0.01 ? "under 1%" : v > 0.99 && v < 1 ? "over 99%" : `${Math.round(v * 100)}%`);
    const list = (ps) => { const n = ps.map(name); return n.length > 1 ? n.slice(0, -1).join(", ") + " and " + n[n.length - 1] : n[0]; };
    const R = list(b.right), Lb = list(b.left), K = name(b.kingmaker);
    const vals = Object.values(H0);   // right alone, left alone, kingmaker decides, neither
    $("#answer").textContent = `${R} win a majority on their own in ${pc(vals[0])} of simulations. ` +
      (vals[1] >= 0.05 ? `${Lb} do in ${pc(vals[1])}. ` : "") +
      `In ${pc(vals[2])}, neither side does and ${K} holds the balance.`;

    // Around the chamber from the foot of the left arm to the foot of the right arm:
    // the two major parties sit at the foot of each arm, nearest the Speaker, and the
    // smaller parties further round towards the curve.
    const ORDER = ["LAB", "GRN", "TPM", "OPP", "NZF", "ACT", "NAT"];
    const seatsBy = ORDER.filter((p) => S.seats[p]).map((p) => ({ p, n: S.seats[p].median }));
    const N = d3.sum(seatsBy, (d) => d.n);
    const el = $("#house-chart");
    // Horseshoe, like the Debating Chamber: two straight arms joined by a curve, open end
    // (the Speaker's chair) at the bottom. Seats run from the foot of the left arm, round
    // the curve, to the foot of the right arm, so blocs form wedges and the Speaker's
    // right is the right-hand side of the picture.
    const rows = 3, W = 600, R1 = 240, L = 210, top = 34;
    const g = (2 * rows * L + Math.PI * rows * R1) / (N + Math.PI * rows * (rows - 1) / 2);
    const radii = d3.range(rows).map((k) => R1 - k * g);
    const Rm = d3.mean(radii), cx = W / 2, yc = top + R1, Hh = yc + L + 28;
    const lens = radii.map((r) => 2 * L + Math.PI * r);
    let per = lens.map((l) => Math.round((N * l) / d3.sum(lens)));
    let diff = N - d3.sum(per);
    for (let i = 0; diff !== 0; i = (i + 1) % rows) { per[i] += Math.sign(diff); diff -= Math.sign(diff); }
    const pos = [];
    radii.forEach((r, k) => {
      const len = lens[k];
      for (let j = 0; j < per[k]; j++) {
        const sAlong = ((j + 0.5) / per[k]) * len;
        let x, y, u;
        if (sAlong < L) { x = cx - r; y = yc + L - sAlong; u = sAlong; }
        else if (sAlong < L + Math.PI * r) { const ph = (sAlong - L) / r; x = cx - r * Math.cos(ph); y = yc - r * Math.sin(ph); u = L + ph * Rm; }
        else { const s2 = sAlong - L - Math.PI * r; x = cx + r; y = yc + s2; u = L + Math.PI * Rm + s2; }
        pos.push({ x, y, u, r });
      }
    });
    pos.sort((a, b) => a.u - b.u || b.r - a.r);
    let k = 0;
    seatsBy.forEach((d) => { for (let i = 0; i < d.n; i++) pos[k++].p = d.p; });
    const dotR = g * 0.4;
    const svg = d3.select(el).append("svg").attr("viewBox", `0 0 ${W} ${Hh}`).attr("role", "img")
      .attr("aria-label", `Projected House of ${N} seats: ` + seatsBy.map((d) => `${name(d.p)} ${d.n}`).join(", "));
    svg.selectAll("circle").data(pos).join("circle").attr("cx", (d) => d.x).attr("cy", (d) => d.y)
      .attr("r", dotR).attr("fill", (d) => colour(d.p))
      .on("pointermove", (ev, d) => showTip(`<div class="t-head">${sw(d.p)} ${name(d.p)}</div>${S.seats[d.p].median} seats (90% interval ${S.seats[d.p].lo}–${S.seats[d.p].hi})`, ev))
      .on("pointerleave", hideTip);
    // Speaker's chair at the open end
    svg.append("rect").attr("x", cx - 9).attr("y", yc + L + 2).attr("width", 18).attr("height", 12).attr("rx", 2)
      .attr("fill", "none").attr("stroke", "var(--muted)").attr("stroke-width", 1.5);
    svg.append("text").attr("x", cx).attr("y", yc + L + 26).attr("text-anchor", "middle").attr("font-size", 12)
      .attr("fill", "var(--muted)").text("Speaker");
    const maj = Math.floor(N / 2) + 1;
    svg.append("line").attr("x1", cx).attr("x2", cx).attr("y1", top - 12).attr("y2", yc - radii[rows - 1] + dotR + 6)
      .attr("stroke", "var(--ink)").attr("stroke-width", 1.5).attr("stroke-dasharray", "3 3");
    svg.append("text").attr("x", cx).attr("y", top - 18).attr("text-anchor", "middle").attr("font-size", 14)
      .attr("font-weight", 700).attr("fill", "var(--ink)").text(`${maj} for a majority`);
    svg.append("text").attr("x", cx).attr("y", yc + 18).attr("text-anchor", "middle").attr("font-size", 48)
      .attr("font-weight", 800).attr("fill", "var(--ink)").attr("letter-spacing", "-0.02em").text(N);
    svg.append("text").attr("x", cx).attr("y", yc + 40).attr("text-anchor", "middle").attr("font-size", 14)
      .attr("fill", "var(--muted)").text("seats");
    const over = N - 120;
    $("#house-cap").innerHTML = `<div class="legend">${seatsBy.map((d) => `<span>${sw(d.p)}${name(d.p)} <b>${d.n}</b></span>`).join("")}</div>` +
      `Median seats in each party's simulations. Labour and National sit at the foot of each side, nearest the Speaker.${over > 0 ? ` The House is ${N} seats because of a ${over}-seat overhang.` : ""}`;
  })();

  const H = S.headline;
  const hRows = Object.entries(H).map(([k, v]) => {
    const label = k.replace("Right bloc", blocName(S.meta.blocs.right)).replace("Left bloc", blocName(S.meta.blocs.left))
      .replace(S.meta.blocs.kingmaker, name(S.meta.blocs.kingmaker));
    return `<div class="prob-row"><div>${label}</div><div class="bar"><i style="width:${v * 100}%"></i></div><div class="pct">${Math.round(v * 100)}%</div></div>`;
  });
  $("#headline").innerHTML = hRows.join("");
  $("#coalitions").innerHTML = S.coalitions.map((c) =>
    `<div class="prob-row"><div><div class="who">${c.parties.map(sw).join("")} ${c.name}</div><div class="detail">median ${c.median} seats (${c.lo}–${c.hi})</div></div>
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
  const pRow = (pr) => Object.entries(pr).sort((a, b) => b[1] - a[1]).map(([p, v]) => `${sw(p)} ${name(p)} ${v < 0.01 && v > 0 ? "<1" : Math.round(v * 100)}%`).join(" &nbsp; ");
  const keyRows = Object.entries(A.general_key_seats || {});
  $("#assumptions").innerHTML = `${keyRows.length ? `<p>General electorates where a party other than National or Labour has a real chance, with their simulated chances (from the electorate model below):</p>
    <div class="table-wrap"><table class="data"><thead><tr><th class="l">Electorate</th><th class="l">Chance of winning</th></tr></thead><tbody>${
      keyRows.map(([e, pr]) => `<tr><td>${e}</td><td class="l">${pRow(pr)}</td></tr>`).join("")}</tbody></table></div>` : ""}
    <p>Māori electorates (stated assumptions, at each party's current median vote):</p>
    <div class="table-wrap"><table class="data"><thead><tr><th class="l">Electorate</th><th class="l">Assumed chance of winning</th></tr></thead><tbody>${
      Object.entries(A.maori || A.probabilities || {}).map(([e, pr]) => `<tr><td>${e}</td><td class="l">${pRow(pr)}</td></tr>`).join("")}</tbody></table></div>`;

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
    const sc = ELEC.scenario, prob = ELEC.n_draws > 0;
    const EP = ["NAT", "LAB", "GRN", "ACT", "NZF", "OPP"];
    $("#elec-sub").innerHTML = prob
      ? `Chances in the 64 general electorates (2026 boundaries), from ${d3.format(",")(ELEC.n_draws)} simulations. Each one takes a draw of the national vote from the poll of polls, applies every voting place's lean, models the candidate vote, and adds the local error the model has made in past elections. Candidates are assumed to be those who stood in ${ELEC.base_year}. Māori electorates aren't modelled here.`
      : `Projected winners in the 64 general electorates (2026 boundaries) at today's poll-of-polls median: ${["NAT", "LAB", "GRN", "ACT", "NZF", "OPP"].map((p) => `${name(p)} ${fmt1(sc[p])}%`).join(", ")}. Candidates are assumed to be those who stood in ${ELEC.base_year}. Māori electorates aren't modelled here.`;
    const rating = (p) => (p >= 0.95 ? "Safe" : p >= 0.75 ? "Likely" : p >= 0.6 ? "Leans" : "Toss-up");
    const tidy = (n) => { if (!n) return "–"; const [s2, g] = n.split(","); if (!g) return n; const first = g.trim().split(" ")[0]; return `${first} ${s2.charAt(0) + s2.slice(1).toLowerCase()}`; };
    const pbar = (pw) => `<span class="pbar" aria-hidden="true">${EP.filter((p) => pw[p] > 0).map((p) => `<i style="width:${pw[p] * 100}%;background:${colour(p)}"></i>`).join("")}</span>`;
    const draw = () => {
      const m = $("#elec-method").value, q = $("#elec-search").value.trim().toLowerCase();
      if (prob) {
        const sc2 = ELEC.sim_counts[m];
        $("#elec-counts").innerHTML = Object.entries(sc2).filter(([, v]) => v.hi > 0).sort((a, b) => b[1].median - a[1].median)
          .map(([p, v]) => `<div class="tile"><div class="name">${sw(p)}${name(p)}</div><div class="val">${v.median}</div><div class="int">${v.lo}–${v.hi} seats</div></div>`).join("");
      } else {
        $("#elec-counts").innerHTML = Object.entries(ELEC.counts[m]).filter(([, v]) => v > 0).sort((a, b) => b[1] - a[1])
          .map(([p, v]) => `<div class="tile"><div class="name">${sw(p)}${name(p)}</div><div class="val">${v}</div></div>`).join("");
      }
      let rows = ELEC.seats.filter((s) => !q || s.seat.toLowerCase().includes(q)).map((s) => {
        const r = s[m];
        const pw = r.p_win || { [r.winner]: 1 };
        const fav = Object.entries(pw).sort((a, b) => b[1] - a[1])[0];
        return { ...s, r, pw, fav: fav[0], pfav: fav[1] };
      });
      rows.sort((a, b) => (prob ? a.pfav - b.pfav : a.r.margin - b.r.margin));
      const total = rows.length;
      if (!showAllSeats && !q) rows = rows.slice(0, 20);
      const cell = (r, p) => {
        const qv = r.cand_q?.[p];
        return qv ? `<td>${fmt1(qv[1])}<span class="q">${Math.round(qv[0])}–${Math.round(qv[2])}</span></td>` : `<td>${pct(r.candidate[p])}</td>`;
      };
      $("#electable").innerHTML = `<table class="data"><thead><tr><th class="l">Electorate</th><th class="l">Favourite</th>${prob ? '<th class="l">Chance of winning</th>' : "<th>Margin</th>"}${
        ["NAT", "LAB", "GRN", "ACT"].map((p) => `<th>${sw(p)} ${name(p)} candidate</th>`).join("")}</tr></thead><tbody>${
        rows.map((s) => {
          const tipTxt = EP.filter((p) => s.pw[p] >= 0.005).map((p) => `${name(p)} ${Math.round(s.pw[p] * 100)}%`).join(", ");
          return `<tr title="Assumed candidates: ${tidy(s.assumed.NAT)} (National), ${tidy(s.assumed.LAB)} (Labour)"><td>${s.seat}</td>
          <td class="l">${sw(s.fav)} ${name(s.fav)}${prob ? ` <span class="muted">${rating(s.pfav)}</span>` : ""}</td>
          ${prob ? `<td class="l"><span class="chance">${pbar(s.pw)}<b>${s.pfav > 0.995 ? ">99" : Math.round(s.pfav * 100)}%</b></span><span class="sr">${tipTxt}</span></td>` : `<td>${fmt1(s.r.margin)}</td>`}
          ${["NAT", "LAB", "GRN", "ACT"].map((p) => cell(s.r, p)).join("")}</tr>`;
        }).join("")
      }</tbody></table><p class="note">${prob
        ? "Sorted from most to least uncertain. The bar splits each seat's chances by party. Candidate votes are medians with 90% intervals. Hover a row to see the assumed candidates."
        : "Sorted from closest to safest. Hover a row to see the assumed candidates."}</p>${rows.length < total ? `<button class="more" id="more-seats">Show all ${total} electorates</button>` : ""}`;
      $("#more-seats")?.addEventListener("click", () => { showAllSeats = true; draw(); });
    };
    let showAllSeats = false;
    $("#elec-method").addEventListener("change", draw);
    $("#elec-search").addEventListener("input", draw);
    draw();

    // method text: backtest
    if (ELEC.backtest?.recent) {
      const bt = ELEC.backtest.recent.map((b) => `${b.correct} of ${b.of} in ${b.year}`).join(", ");
      const le = ELEC.local_error.recent;
      $("#elec-method-note").innerHTML = `Given the actual national result, the electorate model (recent lean) picked the winner in ${bt}. In those backtests a major party's candidate vote was off by about ${fmt1(le.seat_sd[0])} points (National) and ${fmt1(le.seat_sd[1])} points (Labour) in a typical seat, plus a shared miss of about ${fmt1(le.year_sd[0])}–${fmt1(le.year_sd[1])} points that moved every seat the same way that year. The simulations add errors of that size. Checked year by year on elections they weren't calibrated on, favourites won about as often as their probabilities said, though seats rated near-certain were upset slightly more often than predicted (4 of 139).`;
    }
  })();

  // redraw trend on resize
  let rt;
  window.addEventListener("resize", () => { clearTimeout(rt); rt = setTimeout(() => drawTrend(rangeKey), 200); });
})();
