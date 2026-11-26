"use strict";

const get = (id) => document.getElementById(id);
const state = {card: null, result: null, photo: null, probe: null, mode: "probe", chart: "profile", busy: false,
  cards: [], compare: null, paired: null, markFirst: null, markSecond: null};
const settings = [...document.querySelectorAll("[data-setting]")];
const limits = [...document.querySelectorAll("[data-limit]")];

async function api(path, options) {
  const response = await fetch("/saltmark" + path, options);
  const body = await response.json();
  if (!response.ok) throw new Error(body.error || "请求失败，请检查输入后重试。");
  return body;
}

function route(tail) {
  return "/cards/" + state.card.id + tail;
}

function savedQuery() {
  return "?revision=" + state.card.revision;
}

function notice(message, target = "notice") {
  const element = get(target);
  element.textContent = message;
  element.hidden = !message;
}

async function action(work, target = "notice") {
  if (state.busy) return;
  state.busy = true;
  document.querySelectorAll("button, select").forEach((node) => { node.disabled = true; });
  notice("", target);
  try {
    await work();
  } catch (error) {
    notice(error.message, target);
  } finally {
    state.busy = false;
    document.querySelectorAll("button, select").forEach((node) => { node.disabled = false; });
  }
}

async function library() {
  const {cards} = await api("/cards");
  state.cards = cards;
  const select = get("library");
  select.replaceChildren(new Option("选取已存卡片", ""));
  for (const card of cards) select.append(new Option(card.name, card.id));
  select.value = state.card?.id || "";
}

function paintSource() {
  const canvas = get("capture");
  const ctx = canvas.getContext("2d");
  const {photo,card,probe,result} = state;
  if (!photo) return;
  canvas.width = card.width;
  canvas.height = card.height;
  ctx.drawImage(photo,0,0);
  const cfg = card.settings;
  ctx.strokeStyle = "#78b6a9";
  ctx.lineWidth = 2;
  ctx.setLineDash([5,5]);
  ctx.strokeRect(cfg.left,cfg.top,cfg.right-cfg.left,cfg.bottom-cfg.top);
  ctx.setLineDash([]);
  if (result.profile.length) {
    ctx.strokeStyle = "#aac4d7";
    ctx.beginPath();
    ctx.moveTo(cfg.left,result.focus);
    ctx.lineTo(cfg.right,result.focus);
    ctx.stroke();
  }
  ctx.fillStyle = "#ffdc8c";
  for (const p of result.profile) {
    if (p.pale) ctx.fillRect(p.x,p.y - 1,1,3);
  }
  if (probe) {
    ctx.strokeStyle = "#faf1e2";
    ctx.strokeRect(probe.x - 5,probe.y - 5,10,10);
  }
}

function paintChart() {
  const canvas = get("chart");
  const ctx = canvas.getContext("2d");
  const {width,height} = canvas;
  const {result,card} = state;
  const cfg = card.settings;
  const coverage = state.chart === "coverage";
  const lo = coverage ? cfg.top : cfg.left;
  const hi = coverage ? cfg.bottom : cfg.right;
  const upper = coverage ? 100 : 255;
  const xAt = (x) => 48 + (width - 84) * (x - lo) / Math.max(1,hi - lo);
  const yAt = (v) => height - 26 - (height - 44) * v / upper;
  get("chart-title").textContent = coverage ? "各原行浅色占比" : "原行浅色证据";
  get("chart-caption").textContent = coverage ? "实际浅色比例 % · 原片 Y" : "原片 X · 最低RGB分量";
  ctx.fillStyle = "#faf7ef";
  ctx.fillRect(0,0,width,height);
  ctx.font = "12px monospace";
  ctx.fillStyle = "#64534a";
  ctx.strokeStyle = "#e8dbc9";
  for (const level of [0,Math.round(upper/2),upper]) {
    ctx.fillText(level,8,yAt(level)+3);
    ctx.beginPath();
    ctx.moveTo(xAt(lo),yAt(level));
    ctx.lineTo(xAt(hi),yAt(level));
    ctx.stroke();
  }
  ctx.fillText(String(lo),xAt(lo),height-7);
  ctx.fillText(String(hi),xAt(hi)-15,height-7);
  ctx.strokeStyle = "#786760";
  ctx.lineWidth = 2;
  const data = coverage ? result.rows.map((row) => [row.y,100*row.fraction])
    : result.profile.map((point) => [point.x,point.floor]);
  ctx.beginPath();
  data.forEach(([pos,value],i) => {
    if (i) ctx.lineTo(xAt(pos),yAt(value));
    else ctx.moveTo(xAt(pos),yAt(value));
  });
  ctx.stroke();
  if (!coverage) {
    ctx.strokeStyle = "#a66c43";
    ctx.setLineDash([5,4]);
    ctx.beginPath();
    ctx.moveTo(xAt(lo),yAt(cfg.minimum));
    ctx.lineTo(xAt(hi),yAt(cfg.minimum));
    ctx.stroke();
    ctx.setLineDash([]);
    ctx.fillStyle = "#aa7448";
    for (const p of result.profile) {
      if (p.pale) ctx.fillRect(xAt(p.x),yAt(p.floor)-2,2,4);
    }
  }
}

function pointLabel(point) {
  const disposition = point.pale === null ? "框外" : (point.pale ? "近中性浅色" : "条件未达");
  return "(" + point.x + ", " + point.y + ") · RGB " + point.rgb.join("/") +
    " · 亮度 " + point.brightness.toFixed(2) + " · 最低 " + point.floor +
    " · 通道差 " + point.spread + " · " + disposition;
}

async function show() {
  const {card, result} = state;
  get("workspace").hidden = false;
  get("empty").hidden = true;
  get("origin").textContent = (card.synthetic ? "合成练习图" : "导入原片") + " · 修订 " + card.revision;
  get("card-title").textContent = card.name;
  get("dimensions").textContent = card.width + " × " + card.height + " px · " + card.photo_name;
  get("name").value = card.name;
  for (const field of settings) field.value = card.settings[field.dataset.setting];
  get("probe-x").max = card.width - 1;
  get("probe-y").max = card.height - 1;
  get("probe-x").value = state.probe?.x ?? Math.round((card.settings.left + card.settings.right)/2);
  get("probe-y").value = state.probe?.y ?? result.focus;
  get("probe-result").textContent = state.probe ? pointLabel(state.probe) : "选择原片像素";
  const reading = result.reading;
  get("cover-value").textContent = reading ? (reading.fraction * 100).toFixed(2) : "—";
  get("cover-unit").textContent = "%";
  get("measurement-state").textContent = "原片 Y " + result.focus;
  get("selected-level").textContent = reading
    ? "本行 " + reading.pale_pixels + " / " + reading.pixels + " 个近中性浅色实点"
    : "本行位于测量框外";
  get("area-level").textContent = "全框 " + result.area.pale_pixels + " / " + result.area.pixels +
    " · " + (result.area.fraction * 100).toFixed(2) + "%";
  for (const [id, filename] of Object.entries({proof: "proof.png", csv: "profile.csv", zip: "observation.zip"})) {
    get(id).href = "/saltmark" + route("/export/" + filename) + savedQuery();
  }
  paintSource();
  paintChart();
  renderPartner(card, pairingOf(card));
  await refreshComparison();
}

async function open(card) {
  const base = "/cards/" + card.id;
  const photo = new Image();
  photo.src = "/saltmark" + base + "/capture.png";
  const [result] = await Promise.all([api(base + "/measurement?revision=" + card.revision), photo.decode()]);
  Object.assign(state, {card, result, photo, probe: null, compare: null, paired: null,
    markFirst: null, markSecond: null});
  get("library").value = card.id;
  await libraryNames();
  await show();
}

async function libraryNames() {
  if (!state.cards.length) await library();
}

async function probe(x, y) {
  state.probe = await api(route("/probe") + savedQuery() + "&x=" + x + "&y=" + y);
  get("probe-x").value = x;
  get("probe-y").value = y;
  get("probe-result").textContent = pointLabel(state.probe);
  paintSource();
}

get("practice").addEventListener("click", () => action(async () => {
  await open(await api("/practice", {method: "POST"}));
  await library();
}));

get("library").addEventListener("change", () => {
  if (get("library").value) action(async () => open(await api("/cards/" + get("library").value)));
});
get("open-import").addEventListener("click", () => {
  notice("", "import-notice");
  get("import").showModal();
});
get("cancel-import").addEventListener("click", () => get("import").close());
get("upload").addEventListener("submit", (event) => {
  event.preventDefault();
  action(async () => {
    const card = await api("/cards", {method: "POST", body: new FormData(event.target)});
    await open(card);
    await library();
    get("import").close();
    event.target.reset();
  }, "import-notice");
});
document.querySelectorAll("[data-mode]").forEach((button) => button.addEventListener("click", () => {
  state.mode = button.dataset.mode;
  document.querySelectorAll("[data-mode]").forEach((item) =>
    item.setAttribute("aria-pressed", String(item === button)));
}));
get("capture").addEventListener("click", (event) => {
  if (!state.card) return;
  const canvas = event.currentTarget;
  const rect = canvas.getBoundingClientRect();
  const x = Math.max(0, Math.min(canvas.width - 1, Math.floor((event.clientX - rect.left) * canvas.width / rect.width)));
  const y = Math.max(0, Math.min(canvas.height - 1, Math.floor((event.clientY - rect.top) * canvas.height / rect.height)));
  action(async () => {
    await probe(x, y);
    if (state.mode === "mark") {
      settings.find((field) => field.dataset.setting === "focus").value = y;
      notice("已填入实际原片截线。");
    }
  });
});
get("probe-form").addEventListener("submit", (event) => {
  event.preventDefault();
  action(() => probe(get("probe-x").value, get("probe-y").value));
});
get("calibration").addEventListener("submit", (event) => {
  event.preventDefault();
  action(async () => {
    const fields = Object.fromEntries(settings.map((field) => [
      field.dataset.setting, Number(field.value),
    ]));
    const card = await api(route(""), {
      method: "PATCH", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({revision: state.card.revision, name: get("name").value, settings: fields}),
    });
    await open(card);
    await library();
  });
});
get("prepare").addEventListener("click", () => action(async () => {
  const {url} = await api(route("/prepare") + savedQuery(), {method: "POST"});
  location.assign(url);
}));
document.querySelectorAll("[data-chart]").forEach((button) => button.addEventListener("click", () => {
  state.chart = button.dataset.chart;
  document.querySelectorAll("[data-chart]").forEach((item) =>
    item.setAttribute("aria-pressed", String(item === button)));
  if (state.card) paintChart();
}));

const pairColors = {added: "#4f8a5b", reduced: "#a8513f", unchanged: "#8b7f70", unproven: "#c8a441"};
const emptyPairing = () => ({second: null, limits: {shift: 32, residual: 2, visible: 24}, marks: []});

function pairingOf(card) {
  return card.pairing || emptyPairing();
}

function renderMarks(marks) {
  const rows = get("mark-rows");
  rows.replaceChildren();
  marks.forEach((mark, index) => {
    const row = document.createElement("div");
    row.className = "mark-row";
    row.append(Object.assign(document.createElement("span"), {
      textContent: `${index + 1}. 第一张 X ${mark.first} → 第二张 X ${mark.second}（差 ${mark.second - mark.first}）`,
    }));
    const remove = document.createElement("button");
    remove.type = "button";
    remove.textContent = "删除";
    remove.addEventListener("click", () => action(async () => {
      await savePairing({marks: pairingOf(state.card).marks.filter((_, at) => at !== index), shift: null});
    }));
    row.append(remove);
    rows.append(row);
  });
  if (!marks.length) rows.append(Object.assign(document.createElement("p"),
    {className: "muted", textContent: "还没有固定印记对。"}));
}

function renderPartner(card, pairing) {
  const select = get("partner");
  select.replaceChildren(new Option("选择第二张砖样卡", ""));
  for (const item of state.cards) if (item.id !== card.id) select.append(new Option(item.name, item.id));
  select.value = pairing.second || "";
  const target = state.cards.find((item) => item.id === pairing.second);
  get("partner-origin").textContent = target
    ? "第二张：修订 " + target.revision + (target.synthetic ? " · 合成练习图" : " · 导入原片")
    : "为同一块砖选第二张砖样卡。";
}

function compareShape(box, card) {
  const canvas = get(box);
  canvas.width = card.width;
  canvas.height = card.height;
  return canvas.getContext("2d");
}

async function loadImages() {
  const key = state.compare.first.id + ":" + state.compare.second.id;
  if (state.images?.key === key) return state.images;
  const first = new Image();
  first.src = "/saltmark/cards/" + state.compare.first.id + "/capture.png";
  const second = new Image();
  second.src = "/saltmark" + route("/partner.png");
  await Promise.all([first.decode(), second.decode()]);
  state.images = {key, first, second};
  return state.images;
}

function paintComparison() {
  const compare = state.compare;
  if (!compare) return;
  const firstCtx = compareShape("compare-first", compare.first);
  const secondCtx = compareShape("compare-second", compare.second);
  firstCtx.drawImage(state.images.first, 0, 0);
  secondCtx.drawImage(state.images.second, 0, 0);
  get("first-line-label").textContent = "截线 Y " + compare.first.line + " · 阈值 ≥" + compare.first.settings.minimum +
    " / Δ≤" + compare.first.settings.spread;
  get("second-line-label").textContent = "截线 Y " + compare.second.line + " · 阈值 ≥" + compare.second.settings.minimum +
    " / Δ≤" + compare.second.settings.spread;
  for (const [ctx, line] of [[firstCtx, compare.first.line], [secondCtx, compare.second.line]]) {
    ctx.strokeStyle = "#aac4d7";
    ctx.beginPath();
    ctx.moveTo(0, line);
    ctx.lineTo(ctx.canvas.width, line);
    ctx.stroke();
  }
  for (const point of compare.evidence.points) {
    firstCtx.fillStyle = pairColors[point.status];
    firstCtx.fillRect(point.first_x, compare.first.line - 1, 1, 3);
    secondCtx.fillStyle = pairColors[point.status];
    secondCtx.fillRect(point.second_x, compare.second.line - 1, 1, 3);
  }
  for (const mark of compare.marks) {
    firstCtx.strokeStyle = "#faf1e2";
    firstCtx.strokeRect(mark.first - 4, compare.first.line - 8, 8, 16);
    secondCtx.strokeStyle = "#faf1e2";
    secondCtx.strokeRect(mark.second - 4, compare.second.line - 8, 8, 16);
  }
  const paired = state.paired;
  if (paired?.first) {
    firstCtx.strokeStyle = "#ffe09d";
    firstCtx.strokeRect(paired.first.x - 5, paired.first.y - 5, 10, 10);
    if (paired.second) {
      secondCtx.strokeStyle = "#ffe09d";
      secondCtx.strokeRect(paired.second.x - 5, paired.second.y - 5, 10, 10);
    }
  }
  const counts = compare.evidence.counts;
  get("shift-value").textContent = compare.selected;
  get("solution-detail").textContent = "共见 " + counts.co_visible + " · 真原点重叠 " + compare.best.true_overlap +
    " · 实标剩余偏差 " + compare.best.max_residual + " px";
  get("evidence-counts").textContent = "共见 " + counts.co_visible + " · 新增 " + counts.added + " · 减少 " +
    counts.reduced + " · 未变 " + counts.unchanged + " · 无证 " + counts.unproven;
  get("compare-state").textContent = "位移 " + compare.selected + " px · 候选 " + compare.candidate_count +
    (compare.adopted === compare.selected ? " · 已采用" : " · 候选解");
  paintCandidates();
  paintEvidence();
  paintCrops();
}

function paintCrops() {
  const paired = state.paired;
  get("paired-crops").hidden = !(paired?.first);
  if (!paired?.first) return;
  const draw = (box, image, point) => {
    const canvas = get(box);
    const ctx = canvas.getContext("2d");
    ctx.fillStyle = "#3d3431";
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    if (!image || !point) {
      ctx.fillStyle = "#f3eade";
      ctx.font = "11px monospace";
      ctx.fillText("范围外", 8, canvas.height / 2);
      return;
    }
    const size = 120, half = 7;
    const sx = Math.max(0, point.x - half), sy = Math.max(0, point.y - half);
    ctx.drawImage(image, sx, sy, half * 2, half * 2, 0, 0, size, size);
    ctx.strokeStyle = "#ffe09d";
    ctx.lineWidth = 2;
    ctx.strokeRect(size / 2 - 9, size / 2 - 9, 18, 18);
  };
  draw("crop-first", state.images?.first, paired.first);
  draw("crop-second", state.images?.second, paired.second);
}

function paintCandidates() {
  const compare = state.compare;
  const body = get("candidates").querySelector("tbody");
  body.replaceChildren();
  for (const row of compare.candidates) {
    const tr = document.createElement("tr");
    tr.setAttribute("aria-selected", String(row.shift === compare.selected));
    for (const value of [row.shift, row.score.toFixed(3), row.true_overlap, row.co_visible, row.max_residual]) {
      tr.append(Object.assign(document.createElement("td"), {textContent: value}));
    }
    const cell = document.createElement("td");
    const adopt = document.createElement("button");
    adopt.type = "button";
    adopt.textContent = "采用";
    adopt.disabled = row.shift === compare.selected;
    adopt.addEventListener("click", () => action(async () => {
      await savePairing({shift: row.shift});
      notice("已采用位移 " + row.shift + " px。", "pairing-notice");
    }));
    cell.append(adopt);
    tr.append(cell);
    body.append(tr);
  }
}

function paintEvidence() {
  const canvas = get("evidence-chart");
  const ctx = canvas.getContext("2d");
  const {width, height} = canvas;
  const points = state.compare.evidence.points;
  ctx.fillStyle = "#faf7ef";
  ctx.fillRect(0, 0, width, height);
  if (!points.length) return;
  const xs = points.map((point) => point.first_x);
  const lo = Math.min(...xs), hi = Math.max(...xs);
  const xAt = (x) => 30 + (width - 46) * (x - lo) / Math.max(1, hi - lo);
  const bar = Math.max(1, (width - 46) / Math.max(1, points.length));
  ctx.font = "11px monospace";
  ctx.fillStyle = "#64534a";
  ctx.fillText(String(lo), 4, height - 5);
  ctx.fillText(String(hi), width - 32, height - 5);
  for (const point of points) {
    ctx.fillStyle = pairColors[point.status];
    ctx.fillRect(Math.round(xAt(point.first_x)), 14, bar, height - 32);
  }
}

function pairedLabel(paired) {
  if (!paired) return "点第一张原截面，切到第二张读数。";
  const first = paired.first;
  const second = paired.second;
  const own = `第一张 (${first.x}, ${first.y}) RGB ${first.rgb.join("/")} 最低 ${first.floor} Δ${first.spread} · ${first.pale ? "浅色" : "未达"}`;
  if (!second) return own + " → 第二张范围外，无证。";
  const mate = `第二张 (${second.x}, ${second.y}) RGB ${second.rgb.join("/")} 最低 ${second.floor} Δ${second.spread} · ${second.pale ? "浅色" : "未达"}`;
  return own + " → " + mate + " · " + paired.label;
}

async function refreshComparison() {
  const pairing = pairingOf(state.card);
  if (!pairing.second) {
    get("compare").hidden = false;
    state.compare = null;
    state.paired = null;
    get("compare-state").textContent = "";
    get("paired-readout").textContent = pairedLabel(null);
    get("candidates").querySelector("tbody").replaceChildren();
    return;
  }
  get("compare").hidden = false;
  state.compare = await api(route("/comparison"));
  renderMarks(state.compare.marks);
  for (const field of limits) field.value = state.compare.limits[field.dataset.limit];
  get("comparison-csv").hidden = Boolean(state.compare.needs);
  await loadImages();
  if (state.compare.needs) {
    state.paired = null;
    get("shift-value").textContent = "—";
    get("solution-detail").textContent = state.compare.note;
    get("evidence-counts").textContent = "";
    get("compare-state").textContent = state.compare.needs === "marks" ? "待固定印记" : "无可行位移";
    get("paired-readout").textContent = pairedLabel(null);
    get("candidates").querySelector("tbody").replaceChildren();
    paintBlank();
    return;
  }
  get("comparison-csv").href = "/saltmark" + route("/export/comparison.csv");
  paintComparison();
  get("paired-readout").textContent = pairedLabel(state.paired);
}

function paintBlank() {
  const compare = state.compare;
  const contexts = {};
  for (const [box, card, image] of [["compare-first", compare.first, state.images.first],
    ["compare-second", compare.second, state.images.second]]) {
    const ctx = compareShape(box, card);
    contexts[box] = ctx;
    ctx.drawImage(image, 0, 0);
    ctx.strokeStyle = "#aac4d7";
    ctx.beginPath();
    ctx.moveTo(0, card.line);
    ctx.lineTo(ctx.canvas.width, card.line);
    ctx.stroke();
  }
  for (const mark of compare.marks) {
    contexts["compare-first"].strokeStyle = "#faf1e2";
    contexts["compare-first"].strokeRect(mark.first - 4, compare.first.line - 8, 8, 16);
    contexts["compare-second"].strokeStyle = "#faf1e2";
    contexts["compare-second"].strokeRect(mark.second - 4, compare.second.line - 8, 8, 16);
  }
  get("first-line-label").textContent = "截线 Y " + compare.first.line;
  get("second-line-label").textContent = "截线 Y " + compare.second.line;
  get("paired-crops").hidden = true;
  const canvas = get("evidence-chart");
  const ctx = canvas.getContext("2d");
  ctx.fillStyle = "#faf7ef";
  ctx.fillRect(0, 0, canvas.width, canvas.height);
}

async function pairedProbe(x) {
  if (!state.compare) return;
  if (state.compare.needs) {
    notice(state.compare.note || "先保存至少一对固定印记，才能切到第二张读数。");
    return;
  }
  state.paired = await api(route("/comparison/probe") + "?x=" + x);
  get("paired-readout").textContent = pairedLabel(state.paired);
  paintComparison();
}

async function savePairing(patch) {
  const merged = {...pairingOf(state.card), ...patch};
  if (merged.shift === undefined) delete merged.shift;
  const card = await api(route(""), {
    method: "PATCH", headers: {"Content-Type": "application/json"},
    body: JSON.stringify({revision: state.card.revision, pairing: merged}),
  });
  state.card = card;
  await open(card);
}

function pickMark(kind, x) {
  if (kind === "first") state.markFirst = x;
  else state.markSecond = x;
  get("mark-first").value = state.markFirst ?? "";
  get("mark-second").value = state.markSecond ?? "";
  const complete = state.markFirst !== null && state.markSecond !== null;
  notice(complete ? "两张都已点出印记原 X，正在成对保存。"
    : "已点出" + (kind === "first" ? "第一张" : "第二张") + "印记 X，请再点另一张。");
  return complete;
}

async function addMark() {
  const first = Number(get("mark-first").value);
  const second = Number(get("mark-second").value);
  if (!Number.isInteger(first) || !Number.isInteger(second)) {
    notice("请填入两张各自的整数原 X。", "pairing-notice");
    return;
  }
  const marks = [...pairingOf(state.card).marks, {first, second}];
  state.markFirst = state.markSecond = null;
  await savePairing({marks, shift: null});
  notice("已保存一对固定印记。", "pairing-notice");
}

function imageX(canvas, event) {
  const rect = canvas.getBoundingClientRect();
  return Math.max(0, Math.min(canvas.width - 1,
    Math.floor((event.clientX - rect.left) * canvas.width / rect.width)));
}

get("add-mark").addEventListener("click", () => action(addMark));
get("partner").addEventListener("change", () => action(async () => {
  const partner = get("partner").value || null;
  await savePairing({second: partner, shift: null, marks: partner ? pairingOf(state.card).marks : []});
}));
get("pairing").addEventListener("submit", (event) => {
  event.preventDefault();
  action(async () => {
    const fields = Object.fromEntries(limits.map((field) => [field.dataset.limit, Number(field.value)]));
    await savePairing({limits: fields});
    notice("已按上限求解统一整数位移。", "pairing-notice");
  });
});
get("compare-first").addEventListener("click", (event) => {
  if (!state.compare) return;
  const x = imageX(event.currentTarget, event);
  action(async () => {
    const complete = state.mode === "mark" ? pickMark("first", x) : false;
    await pairedProbe(x);
    if (complete) await addMark();
  });
});
get("compare-second").addEventListener("click", (event) => {
  if (!state.compare || state.mode !== "mark") return;
  const x = imageX(event.currentTarget, event);
  if (!state.compare.needs) {
    const firstX = x - state.compare.selected;
    const [lo, hi] = state.compare.evidence.window;
    if (firstX < lo || firstX > hi) {
      notice("第二张该点不在共见范围内。");
      return;
    }
  }
  action(async () => {
    if (pickMark("second", x)) await addMark();
  });
});

action(library);
