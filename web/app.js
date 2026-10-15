// Versão que roda inteiramente no navegador.
// Vídeos: ffmpeg.wasm. Imagens: canvas do navegador (JPG, PNG, WebP, AVIF) ou ffmpeg.wasm (GIF, BMP, TIFF).
import { FFmpeg } from "./vendor/ffmpeg/index.js";

const CORE_BASE = "https://cdn.jsdelivr.net/npm/@ffmpeg/core@0.12.10/dist/esm";

const VIDEO_INPUT = ["mp4", "m4v", "mkv", "webm", "mov", "avi", "wmv", "flv", "mpg", "mpeg", "ts", "m2ts", "3gp", "ogv"];
const VIDEO_OUTPUT = ["mp4", "mkv", "webm", "mov", "avi", "gif"];
const IMAGE_INPUT = ["jpg", "jpeg", "png", "webp", "avif", "gif", "bmp", "tif", "tiff"];
const IMAGE_OUTPUT = ["jpg", "png", "webp", "avif", "gif", "bmp", "tiff"];

// Mesmos valores da versão local (app/video.py e app/image.py).
// Só H.264: o libx265 do ffmpeg.wasm roda sem otimizações e leva minutos por segundo de vídeo.
// H.265 e AV1 ficam para a versão local.
const CRF = { alta: 18, equilibrada: 22, maxima: 26 };
const IMAGE_QUALITY = {
  alta: { jpg: 0.9, webp: 0.9, avif: 0.8 },
  equilibrada: { jpg: 0.82, webp: 0.82, avif: 0.65 },
  maxima: { jpg: 0.7, webp: 0.7, avif: 0.5 },
};
const COPY_VIDEO = { mp4: ["h264", "hevc", "av1", "mpeg4"], mov: ["h264", "hevc", "mpeg4", "prores"] };
const COPY_AUDIO = {
  mp4: ["aac", "mp3", "ac3", "eac3", "alac", "opus", "flac"],
  mov: ["aac", "mp3", "ac3", "alac", "pcm_s16le", "pcm_s24le"],
};
const MIME = {
  mp4: "video/mp4", mkv: "video/x-matroska", webm: "video/webm", mov: "video/quicktime", avi: "video/x-msvideo",
  gif: "image/gif", jpg: "image/jpeg", png: "image/png", webp: "image/webp", avif: "image/avif",
  bmp: "image/bmp", tiff: "image/tiff",
};
const LABELS = { na_fila: "Na fila", processando: "Processando", concluido: "Concluído", erro: "Erro" };

const state = { operation: "compress", canvasFormats: new Set(["jpg", "png", "webp"]) };
const $ = (sel) => document.querySelector(sel);

// ---------- utilidades ----------

function formatBytes(n) {
  const units = ["B", "KB", "MB", "GB"];
  let i = 0;
  while (n >= 1024 && i < units.length - 1) { n /= 1024; i++; }
  return `${n.toFixed(i === 0 ? 0 : 1)} ${units[i]}`;
}

function extOf(name) {
  const i = name.lastIndexOf(".");
  const ext = i < 0 ? "" : name.slice(i + 1).toLowerCase();
  return { jpeg: "jpg", tif: "tiff" }[ext] || ext;
}

function stemOf(name) {
  const i = name.lastIndexOf(".");
  return (i < 0 ? name : name.slice(0, i)) || "arquivo";
}

function kindOf(ext) {
  if (IMAGE_INPUT.includes(ext)) return "image";
  if (VIDEO_INPUT.includes(ext)) return "video";
  return null;
}

async function supportsCanvasFormat(mime) {
  const canvas = document.createElement("canvas");
  canvas.width = canvas.height = 2;
  const blob = await new Promise((r) => canvas.toBlob(r, mime));
  return blob?.type === mime;
}

// ---------- ffmpeg.wasm ----------

let coreFilesPromise = null;
let currentProgress = null;

async function fetchAsBlobURL(url, mime, onProgress) {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`Não foi possível baixar ${url} (${res.status})`);
  const total = Number(res.headers.get("content-length")) || 0;
  const reader = res.body.getReader();
  const chunks = [];
  let loaded = 0;
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    chunks.push(value);
    loaded += value.length;
    if (total && onProgress) onProgress(loaded / total);
  }
  return URL.createObjectURL(new Blob(chunks, { type: mime }));
}

// Baixa o núcleo uma única vez (fica em memória como blob URL).
function getCoreFiles() {
  if (!coreFilesPromise) {
    coreFilesPromise = (async () => {
      const banner = $("#engine");
      banner.hidden = false;
      banner.textContent = "Baixando o FFmpeg (só na primeira vez)…";
      const coreURL = await fetchAsBlobURL(`${CORE_BASE}/ffmpeg-core.js`, "text/javascript");
      const wasmURL = await fetchAsBlobURL(`${CORE_BASE}/ffmpeg-core.wasm`, "application/wasm", (p) => {
        banner.textContent = `Baixando o FFmpeg (só na primeira vez)… ${Math.round(p * 100)}%`;
      });
      banner.hidden = true;
      return { coreURL, wasmURL };
    })().catch((err) => {
      coreFilesPromise = null;
      $("#engine").textContent = "Não foi possível baixar o FFmpeg. Verifique a conexão e tente de novo.";
      throw err;
    });
  }
  return coreFilesPromise;
}

// Cada arquivo usa uma instância nova do FFmpeg: reaproveitar a mesma depois de um
// comando pode corromper a memória do WebAssembly. Iniciar uma instância leva ~1 s.
async function withFFmpeg(fn) {
  const ffmpeg = new FFmpeg();
  ffmpeg.on("progress", ({ progress }) => {
    if (currentProgress && progress >= 0 && progress <= 1) currentProgress(progress);
  });
  await ffmpeg.load(await getCoreFiles());
  try {
    return await fn(ffmpeg);
  } finally {
    ffmpeg.terminate();
  }
}

// Executa o ffmpeg guardando o log para mostrar a causa em caso de erro.
async function runFFmpeg(ffmpeg, args, onProgress) {
  const log = [];
  const onLog = ({ message }) => { log.push(message); if (log.length > 40) log.shift(); };
  ffmpeg.on("log", onLog);
  currentProgress = onProgress;
  try {
    const code = await ffmpeg.exec(["-hide_banner", "-nostdin", "-y", ...args]);
    if (code !== 0) throw new Error("Falha no FFmpeg: " + log.slice(-6).join(" ").slice(-500));
  } finally {
    ffmpeg.off("log", onLog);
    currentProgress = null;
  }
}

async function probe(ffmpeg, input) {
  await ffmpeg.ffprobe(["-v", "error", "-show_entries", "stream=codec_type,codec_name,width,height:format=duration",
    "-of", "json", input, "-o", "probe.json"]);
  const data = JSON.parse(new TextDecoder().decode(await ffmpeg.readFile("probe.json")));
  await ffmpeg.deleteFile("probe.json");
  const streams = data.streams || [];
  const video = streams.find((s) => s.codec_type === "video");
  const audio = streams.find((s) => s.codec_type === "audio");
  if (!video) throw new Error("O arquivo não contém uma faixa de vídeo.");
  return {
    videoCodec: video.codec_name,
    audioCodec: audio ? audio.codec_name : null,
    width: video.width,
  };
}

// ---------- comandos de vídeo (equivalentes a app/video.py) ----------

function videoEncoderArgs(level) {
  // Preset "medium" (a versão local usa "slow"): o ffmpeg.wasm roda em uma só thread.
  return ["-c:v", "libx264", "-preset", "medium", "-crf", String(CRF[level]), "-pix_fmt", "yuv420p"];
}

function audioArgs(info, container = "mp4") {
  if (!info.audioCodec) return [];
  if (COPY_AUDIO[container].includes(info.audioCodec)) return ["-c:a", "copy"];
  return ["-c:a", "aac", "-b:a", "192k"];
}

function compressArgs(input, output, info, level) {
  return ["-i", input, "-map", "0:v:0", "-map", "0:a?", ...videoEncoderArgs(level),
    ...audioArgs(info), "-map_metadata", "0", "-movflags", "+faststart", output];
}

function convertArgs(input, output, info, target, level) {
  if (target === "gif") {
    const width = Math.min(info.width || 640, 640);
    const graph = `fps=15,scale=${width}:-2:flags=lanczos,split[a][b];` +
      "[a]palettegen=stats_mode=diff[p];[b][p]paletteuse=dither=sierra2_4a";
    return ["-i", input, "-filter_complex", graph, "-loop", "0", output];
  }
  if (target === "webm") {
    if (["vp8", "vp9", "av1"].includes(info.videoCodec) && [null, "opus", "vorbis"].includes(info.audioCodec)) {
      return ["-i", input, "-map", "0:v:0", "-map", "0:a?", "-c", "copy", output];
    }
    // VP8: o VP9 do ffmpeg.wasm 0.12 trava (erro de memória). A versão local usa VP9.
    const crf = { alta: "10", equilibrada: "18", maxima: "28" }[level];
    const audio = info.audioCodec ? ["-c:a", "libopus", "-b:a", "128k"] : [];
    return ["-i", input, "-map", "0:v:0", "-map", "0:a?", "-c:v", "libvpx", "-crf", crf, "-b:v", "50M",
      "-deadline", "good", "-cpu-used", "2", ...audio, output];
  }
  if (target === "mkv") {
    return ["-i", input, "-map", "0:v", "-map", "0:a?", "-c", "copy", output];
  }
  if (target === "mp4" || target === "mov") {
    let video;
    if (COPY_VIDEO[target].includes(info.videoCodec)) {
      video = ["-c:v", "copy", ...(info.videoCodec === "hevc" ? ["-tag:v", "hvc1"] : [])];
    } else {
      video = videoEncoderArgs("alta");
    }
    return ["-i", input, "-map", "0:v:0", "-map", "0:a?", ...video, ...audioArgs(info, target),
      "-movflags", "+faststart", output];
  }
  if (target === "avi") {
    const audio = info.audioCodec ? ["-c:a", "libmp3lame", "-q:a", "2"] : [];
    return ["-i", input, "-map", "0:v:0", "-map", "0:a?", ...videoEncoderArgs("alta"), ...audio, output];
  }
  throw new Error(`Formato de vídeo não suportado: ${target}`);
}

async function processVideo(job, onProgress) {
  const input = `entrada.${job.ext}`;
  const output = `saida.${job.target}`;
  return withFFmpeg(async (ffmpeg) => {
    await ffmpeg.writeFile(input, new Uint8Array(await job.file.arrayBuffer()));
    const info = await probe(ffmpeg, input);
    const args = job.operation === "compress"
      ? compressArgs(input, output, info, job.level)
      : convertArgs(input, output, info, job.target, job.level);
    await runFFmpeg(ffmpeg, args, onProgress);
    return new Blob([await ffmpeg.readFile(output)], { type: MIME[job.target] });
  });
}

// ---------- imagens ----------

async function imageWithFFmpeg(job) {
  const input = `entrada.${job.ext}`;
  const output = `saida.${job.target}`;
  const args = ["-i", input];
  if (job.target === "png") {
    // Compressão PNG: sem perdas, ou paleta de 256 cores no nível máximo.
    if (job.level === "maxima") {
      args.push("-filter_complex", "split[a][b];[a]palettegen=max_colors=256:reserve_transparent=1[p];[b][p]paletteuse");
    }
    args.push("-compression_level", "9", "-pred", "mixed");
  } else if (job.target === "gif") {
    args.push("-filter_complex", "split[a][b];[a]palettegen[p];[b][p]paletteuse");
  } else if (job.target === "tiff") {
    args.push("-compression_algo", "lzw");
  } else if (job.target === "jpg") {
    args.push("-q:v", { alta: "2", equilibrada: "4", maxima: "7" }[job.level], "-pix_fmt", "yuvj444p");
  }
  args.push("-frames:v", "1", "-update", "1", output);
  return withFFmpeg(async (ffmpeg) => {
    await ffmpeg.writeFile(input, new Uint8Array(await job.file.arrayBuffer()));
    await runFFmpeg(ffmpeg, args);
    return new Blob([await ffmpeg.readFile(output)], { type: MIME[job.target] });
  });
}

async function imageWithCanvas(job) {
  // createImageBitmap aplica a orientação EXIF da foto.
  const bitmap = await createImageBitmap(job.file, { imageOrientation: "from-image" });
  const canvas = document.createElement("canvas");
  canvas.width = bitmap.width;
  canvas.height = bitmap.height;
  const ctx = canvas.getContext("2d");
  if (job.target === "jpg") {
    // JPG não tem transparência: fundo branco.
    ctx.fillStyle = "#fff";
    ctx.fillRect(0, 0, canvas.width, canvas.height);
  }
  ctx.drawImage(bitmap, 0, 0);
  bitmap.close();
  const quality = IMAGE_QUALITY[job.level][job.target];
  const blob = await new Promise((r) => canvas.toBlob(r, MIME[job.target], quality));
  if (!blob) throw new Error("O navegador não conseguiu gerar a imagem.");
  return blob;
}

async function processImage(job) {
  const canvasInput = job.ext !== "tiff";
  const usesCanvas = canvasInput && state.canvasFormats.has(job.target) && job.target !== "png";
  // PNG sempre passa pelo FFmpeg: o canvas não otimiza a compressão do PNG.
  return usesCanvas ? imageWithCanvas(job) : imageWithFFmpeg(job);
}

// ---------- fila e interface ----------

let queue = Promise.resolve();

function createCard(name) {
  const node = $("#job-template").content.firstElementChild.cloneNode(true);
  node.querySelector(".name").textContent = name;
  node.querySelector(".name").title = name;
  $("#jobs").prepend(node);
  return node;
}

function setState(card, text, cls) {
  const el = card.querySelector(".state");
  el.textContent = text;
  el.classList.toggle("ok", cls === "ok");
  el.classList.toggle("bad", cls === "bad");
}

function setProgress(card, value) {
  card.querySelector(".fill").style.width = `${Math.round(value * 100)}%`;
}

function finish(card, job, blob) {
  let result = blob;
  let note = "";
  // Ao comprimir, nunca devolve um arquivo maior que o original.
  if (job.operation === "compress" && blob.size >= job.file.size && job.target === job.ext) {
    result = job.file;
    note = " (já estava otimizado, mantido o original)";
  }
  const reduction = 1 - result.size / job.file.size;
  let text = `${formatBytes(job.file.size)} → ${formatBytes(result.size)}`;
  if (Math.abs(reduction) < 0.001) text += " (mesmo tamanho)";
  else if (reduction > 0) text += ` (−${(reduction * 100).toFixed(1)}%)`;
  else text += ` (+${(-reduction * 100).toFixed(1)}%, ficou maior)`;
  card.querySelector(".sizes").textContent = text + note;
  const link = card.querySelector(".download");
  link.href = URL.createObjectURL(result);
  link.download = `${stemOf(job.file.name)}_${job.operation === "compress" ? "comprimido" : "convertido"}.${job.target}`;
  link.hidden = false;
  setState(card, LABELS.concluido, "ok");
  setProgress(card, 1);
}

function buildJob(file) {
  const ext = extOf(file.name);
  const kind = kindOf(ext);
  if (!kind) return null;
  const compress = state.operation === "compress";
  let target;
  if (kind === "image") {
    target = compress ? (ext === "bmp" ? "png" : ext) : $("#image-format").value;
  } else {
    target = compress ? "mp4" : $("#video-format").value;
  }
  return {
    file, ext, kind, target,
    operation: state.operation,
    level: compress ? $("#level").value : $("#convert-level").value,
  };
}

function handleFile(file) {
  const card = createCard(file.name);
  const job = buildJob(file);
  if (!job) {
    setState(card, "Formato não suportado", "bad");
    return;
  }
  setState(card, LABELS.na_fila);
  // Um arquivo por vez: o ffmpeg.wasm processa um comando de cada vez.
  queue = queue.then(async () => {
    setState(card, LABELS.processando);
    try {
      const blob = job.kind === "video"
        ? await processVideo(job, (p) => {
          setState(card, `${LABELS.processando} ${Math.round(p * 100)}%`);
          setProgress(card, p);
        })
        : await processImage(job);
      finish(card, job, blob);
    } catch (err) {
      console.error(err);
      setState(card, err?.message || String(err), "bad");
    }
  });
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
    ? "Vídeos saem em MP4 (H.264) com a mesma resolução e taxa de quadros; o áudio é mantido. Imagens ficam no mesmo formato (BMP vira PNG)."
    : "Sempre que possível o vídeo é apenas trocado de contêiner, sem recodificar e sem perda de qualidade.";
}

async function init() {
  if (await supportsCanvasFormat("image/avif")) state.canvasFormats.add("avif");
  const imageOutput = IMAGE_OUTPUT.filter((f) => f !== "avif" || state.canvasFormats.has("avif"));
  fillSelect($("#video-format"), VIDEO_OUTPUT, "mp4");
  fillSelect($("#image-format"), imageOutput, "webp");
  const all = [...VIDEO_INPUT, ...IMAGE_INPUT];
  $("#file-input").accept = all.map((e) => "." + e).join(",");
  $("#accepted").textContent = "Aceita: " + all.join(", ");
}

document.querySelectorAll(".tab").forEach((t) => t.addEventListener("click", () => setOperation(t.dataset.op)));
$("#file-input").addEventListener("change", (e) => { [...e.target.files].forEach(handleFile); e.target.value = ""; });
const dz = $("#dropzone");
["dragenter", "dragover"].forEach((ev) => dz.addEventListener(ev, (e) => { e.preventDefault(); dz.classList.add("over"); }));
["dragleave", "drop"].forEach((ev) => dz.addEventListener(ev, (e) => { e.preventDefault(); dz.classList.remove("over"); }));
dz.addEventListener("drop", (e) => [...e.dataTransfer.files].forEach(handleFile));

setOperation("compress");
init();
