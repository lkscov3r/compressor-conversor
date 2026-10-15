const state = { operation: "compress", info: null };

const $ = (sel) => document.querySelector(sel);
const LABELS = { na_fila: "Na fila", processando: "Processando", concluido: "Concluído", erro: "Erro" };

function formatBytes(n) {
  if (n == null) return "";
  const units = ["B", "KB", "MB", "GB"];
  let i = 0;
  while (n >= 1024 && i < units.length - 1) { n /= 1024; i++; }
  return `${n.toFixed(i === 0 ? 0 : 1)} ${units[i]}`;
}

function extOf(name) {
  const i = name.lastIndexOf(".");
  return i < 0 ? "" : name.slice(i + 1).toLowerCase();
}

function fillSelect(select, values, preferred) {
  select.innerHTML = values.map((v) => `<option value="${v}">${v.toUpperCase()}</option>`).join("");
  if (values.includes(preferred)) select.value = preferred;
}

function setOperation(op) {
  state.operation = op;
  document.querySelectorAll(".tab").forEach((t) => t.classList.toggle("active", t.dataset.op === op));
  document.querySelectorAll("[data-show]").forEach((el) => { el.hidden = el.dataset.show !== op; });
  $("#hint").textContent = op === "compress"
    ? "Vídeos saem em MP4 com a mesma resolução e taxa de quadros; o áudio é mantido. Imagens ficam no mesmo formato (BMP vira PNG)."
    : "Sempre que possível o vídeo é apenas trocado de contêiner, sem recodificar e sem perda de qualidade.";
}

async function loadInfo() {
  const res = await fetch("/api/info");
  state.info = await res.json();
  $("#ffmpeg-warning").hidden = state.info.ffmpeg;
  fillSelect($("#video-format"), state.info.video.output, "mp4");
  fillSelect($("#image-format"), state.info.image.output, "webp");
  const all = [...state.info.video.input, ...state.info.image.input];
  $("#file-input").accept = all.map((e) => "." + e).join(",");
  $("#accepted").textContent = "Aceita: " + all.join(", ");
}

function kindOf(ext) {
  if (state.info.image.input.includes(ext)) return "image";
  if (state.info.video.input.includes(ext)) return "video";
  return null;
}

function createCard(name) {
  const node = $("#job-template").content.firstElementChild.cloneNode(true);
  node.querySelector(".name").textContent = name;
  node.querySelector(".name").title = name;
  $("#jobs").prepend(node);
  return node;
}

function renderJob(card, job) {
  const stateEl = card.querySelector(".state");
  let label = LABELS[job.status] || job.status;
  if (job.status === "processando" && job.kind === "video") label += ` ${Math.round(job.progress * 100)}%`;
  stateEl.textContent = job.status === "erro" ? job.error : label;
  stateEl.classList.toggle("ok", job.status === "concluido");
  stateEl.classList.toggle("bad", job.status === "erro");
  const pct = job.status === "concluido" ? 100 : job.status === "processando" && job.kind === "image" ? 50 : job.progress * 100;
  card.querySelector(".fill").style.width = `${pct}%`;

  if (job.status === "concluido") {
    const r = job.reduction;
    let text = `${formatBytes(job.input_size)} → ${formatBytes(job.output_size)}`;
    if (r != null) text += r >= 0 ? ` (−${(r * 100).toFixed(1)}%)` : ` (+${(-r * 100).toFixed(1)}%, ficou maior)`;
    card.querySelector(".sizes").textContent = text;
    const link = card.querySelector(".download");
    link.href = `/api/jobs/${job.id}/download`;
    link.download = job.download_name;
    link.hidden = false;
  }
}

async function poll(card, id) {
  const res = await fetch(`/api/jobs/${id}`);
  if (!res.ok) return;
  const job = await res.json();
  renderJob(card, job);
  if (job.status === "na_fila" || job.status === "processando") setTimeout(() => poll(card, id), 700);
}

async function submitFile(file) {
  const card = createCard(file.name);
  const kind = kindOf(extOf(file.name));
  const stateEl = card.querySelector(".state");
  if (!kind) {
    stateEl.textContent = "Formato não suportado";
    stateEl.classList.add("bad");
    return;
  }
  const form = new FormData();
  form.append("file", file);
  form.append("operation", state.operation);
  if (state.operation === "compress") {
    form.append("level", $("#level").value);
    form.append("codec", $("#codec").value);
  } else {
    form.append("level", $("#convert-level").value);
    form.append("target_format", kind === "video" ? $("#video-format").value : $("#image-format").value);
    form.append("lossless", $("#lossless").checked);
  }

  stateEl.textContent = "Enviando 0%";
  const job = await new Promise((resolve) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", "/api/jobs");
    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable) stateEl.textContent = `Enviando ${Math.round((e.loaded / e.total) * 100)}%`;
    };
    xhr.onload = () => {
      let body = {};
      try { body = JSON.parse(xhr.responseText); } catch { /* resposta não-JSON */ }
      resolve(xhr.status < 300 ? body : { status: "erro", error: body.detail || `Erro ${xhr.status}` });
    };
    xhr.onerror = () => resolve({ status: "erro", error: "Falha de conexão com o app" });
    xhr.send(form);
  });

  renderJob(card, job);
  if (job.id) poll(card, job.id);
}

function handleFiles(files) {
  [...files].forEach(submitFile);
}

document.querySelectorAll(".tab").forEach((t) => t.addEventListener("click", () => setOperation(t.dataset.op)));
$("#file-input").addEventListener("change", (e) => { handleFiles(e.target.files); e.target.value = ""; });
const dz = $("#dropzone");
["dragenter", "dragover"].forEach((ev) => dz.addEventListener(ev, (e) => { e.preventDefault(); dz.classList.add("over"); }));
["dragleave", "drop"].forEach((ev) => dz.addEventListener(ev, (e) => { e.preventDefault(); dz.classList.remove("over"); }));
dz.addEventListener("drop", (e) => handleFiles(e.dataTransfer.files));

setOperation("compress");
loadInfo();
