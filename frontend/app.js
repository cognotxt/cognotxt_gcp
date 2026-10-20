import { initializeApp } from "https://www.gstatic.com/firebasejs/13.0.0/firebase-app.js";
import { getAuth, signInWithEmailAndPassword, signOut, onAuthStateChanged } from "https://www.gstatic.com/firebasejs/13.0.0/firebase-auth.js";
import { CONFIG } from "./config.js";

const firebaseApp = initializeApp(CONFIG.firebase);
const auth = getAuth(firebaseApp);
const $ = (id) => document.getElementById(id);
const uploadProgress = new Map();
let refreshTimer = null;
// EVOLUTIVA FRONTEND: seleção, filtro e ocultação apenas nesta sessão da interface.
const selectedJobs = new Set();
const hiddenJobs = new Set();
const localFiles = new Map();
let lastJobs = [];
let refreshing = false;


async function token() {
  if (!auth.currentUser) throw new Error("Usuário não autenticado");
  return await auth.currentUser.getIdToken();
}

async function api(path, options={}) {
  const headers = new Headers(options.headers || {});
  headers.set("Authorization", `Bearer ${await token()}`);
  if (options.body && !(options.body instanceof FormData)) headers.set("Content-Type", "application/json");
  const r = await fetch(`${CONFIG.apiBaseUrl}${path}`, {...options, headers});
  if (!r.ok) throw new Error((await r.json().catch(()=>({}))).detail || `HTTP ${r.status}`);
  return r.json();
}

function xhrPut(url, blob, start, end, total) {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("PUT", url, true);
    xhr.setRequestHeader("Content-Type", "application/pdf");
    xhr.setRequestHeader("Content-Range", `bytes ${start}-${end}/${total}`);
    xhr.onload = () => resolve({status:xhr.status, range:xhr.getResponseHeader("Range")});
    xhr.onerror = () => reject(new Error("Falha de rede durante upload"));
    xhr.send(blob);
  });
}

function queryOffset(url, total) {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("PUT", url, true);
    xhr.setRequestHeader("Content-Range", `bytes */${total}`);
    xhr.onload = () => {
      if ([200,201].includes(xhr.status)) return resolve(total);
      if (xhr.status === 308) {
        const range = xhr.getResponseHeader("Range");
        if (!range) return resolve(0);
        const m = range.match(/bytes=0-(\d+)/);
        return resolve(m ? Number(m[1]) + 1 : 0);
      }
      reject(new Error(`Não foi possível consultar o upload: ${xhr.status}`));
    };
    xhr.onerror = () => reject(new Error("Falha ao consultar posição do upload"));
    xhr.send();
  });
}

async function uploadResumable(file, jobId, sessionUrl) {
  const chunkSize = 8 * 1024 * 1024; // múltiplo de 256 KiB
  let offset = 0;
  while (offset < file.size) {
    const endExclusive = Math.min(offset + chunkSize, file.size);
    let attempt = 0;
    while (true) {
      try {
        const result = await xhrPut(sessionUrl, file.slice(offset, endExclusive), offset, endExclusive - 1, file.size);
        if ([200,201].includes(result.status)) {
          offset = file.size;
        } else if (result.status === 308) {
          const m = result.range?.match(/bytes=0-(\d+)/);
          offset = m ? Number(m[1]) + 1 : endExclusive;
        } else {
          throw new Error(`Storage retornou HTTP ${result.status}`);
        }
        uploadProgress.set(jobId, Math.round(offset * 100 / file.size));
        renderJobs(lastJobs);
        break;
      } catch (err) {
        attempt++;
        if (attempt > 5) throw err;
        await new Promise(r => setTimeout(r, Math.min(1000 * 2 ** attempt, 10000)));
        offset = await queryOffset(sessionUrl, file.size);
      }
    }
  }
  uploadProgress.set(jobId, 100);
}

function progressCell(value, klass="", detail="") {
  const pct = Math.max(0, Math.min(100, Number(value || 0)));
  return `<div class="bar ${klass}" role="progressbar" aria-valuenow="${pct}" aria-valuemin="0" aria-valuemax="100"><span style="width:${pct}%"></span></div><div class="pct">${pct}%${detail ? ` · ${escapeHtml(detail)}` : ""}</div>`;
}

function statusText(status) {
  return ({CREATED:"Criado",UPLOADING:"Enviando",UPLOADED:"Recebido",QUEUED:"Na fila",PROCESSING:"Processando",COMPLETED:"Pronto",ERROR:"Erro"})[status] || status || "Criado";
}

function formatBytes(n) {
  if (!Number.isFinite(Number(n)) || Number(n) <= 0) return "Tamanho desconhecido";
  const v = Number(n);
  return v < 1024 * 1024 ? `${(v / 1024).toFixed(0)} KB` : `${(v / (1024 * 1024)).toFixed(1)} MB`;
}

function duration(seconds) {
  if (!Number.isFinite(seconds) || seconds < 0) return "—";
  const n = Math.round(seconds);
  if (n < 60) return `${n}s`;
  return `${Math.floor(n / 60)} min ${String(n % 60).padStart(2, "0")}s`;
}

function secondsBetween(a, b) {
  if (!a || !b) return null;
  const x = Date.parse(a), y = Date.parse(b);
  return Number.isFinite(x) && Number.isFinite(y) ? Math.max(0, (y - x) / 1000) : null;
}

function processingDetail(job) {
  const done = Math.max(0, Number(job.processed_pages || 0));
  const total = Math.max(0, Number(job.total_pages || 0));
  const pages = total > 0 ? `${done} de ${total} págs` : `${done} págs · total identificando`;
  if (job.status === "COMPLETED") {
    const elapsed = secondsBetween(job.started_at, job.finished_at);
    return `${pages} · Concluído em ${duration(elapsed)}`;
  }
  if (job.status === "PROCESSING") {
    const elapsed = secondsBetween(job.started_at, new Date().toISOString());
    if (elapsed === null) return pages;
    // Estimativa baseada na velocidade média real até agora; evita falsas precisões.
    if (done < 3 || elapsed < 5 || total <= 0 || total <= done) return `${pages} · ${duration(elapsed)} decorridos · calculando estimativa`;
    const eta = Math.min(7 * 24 * 3600, (total - done) * elapsed / done);
    return `${pages} · ~${duration(eta)} restantes · ${duration(elapsed)} decorridos`;
  }
  return total > 0 ? pages : "Aguardando contagem de páginas";
}

function visibleJobs() {
  const q = $("searchInput").value.trim().toLocaleLowerCase("pt-BR");
  const status = $("statusFilter").value;
  return lastJobs.filter(j => {
    if (hiddenJobs.has(j.id)) return false;
    if (q && !(j.filename || "").toLocaleLowerCase("pt-BR").includes(q)) return false;
    if (status === "ACTIVE" && !["CREATED", "UPLOADING", "UPLOADED", "QUEUED", "PROCESSING"].includes(j.status)) return false;
    if (!["ALL", "ACTIVE"].includes(status) && j.status !== status) return false;
    return true;
  });
}

function renderJobs(jobs) {
  const byId = new Map(jobs.map(j => [j.id, j]));
  for (const [jobId, pct] of uploadProgress) {
    if (!byId.has(jobId)) byId.set(jobId, {id:jobId, filename:localFiles.get(jobId)?.name || "Upload em andamento", file_size:localFiles.get(jobId)?.size, status:"UPLOADING", upload_progress:pct, processing_progress:0});
  }
  lastJobs = [...byId.values()];
  $("statTotal").textContent = lastJobs.filter(j => !hiddenJobs.has(j.id)).length;
  $("statProcessing").textContent = lastJobs.filter(j => j.status === "PROCESSING" && !hiddenJobs.has(j.id)).length;
  $("statCompleted").textContent = lastJobs.filter(j => j.status === "COMPLETED" && !hiddenJobs.has(j.id)).length;
  $("statErrors").textContent = lastJobs.filter(j => j.status === "ERROR" && !hiddenJobs.has(j.id)).length;

  const visible = visibleJobs();
  const body = $("jobsBody");
  body.innerHTML = "";
  for (const job of visible) {
    const tr = document.createElement("tr");
    // O Storage finalizado é a fonte da confirmação do upload.
    // O Firestore pode manter upload_progress=0, portanto um job já enfileirado/processado precisa exibir 100%.
    const uploaded = ["UPLOADED", "QUEUED", "PROCESSING", "COMPLETED"].includes(job.status);
    const up = uploadProgress.has(job.id) ? uploadProgress.get(job.id) : (uploaded ? 100 : (job.upload_progress ?? 0));
    const total = Number(job.total_pages || 0);
    const meta = [formatBytes(job.file_size ?? localFiles.get(job.id)?.size), total ? `${total} págs` : null].filter(Boolean).join(" · ");
    const done = Math.max(0, Number(job.processed_pages || 0));
    const measured = total && job.status === "PROCESSING" ? Math.max(job.processing_progress || 0, Math.floor(done * 100 / total)) : (job.processing_progress || 0);
    const error = job.error ? `<button class="error-detail" type="button" data-error="${escapeHtml(job.id)}" title="Ver detalhe do erro" aria-label="Ver erro">ⓘ Detalhes</button>` : "";
    tr.innerHTML = `
      <td><input class="job-check" type="checkbox" data-id="${escapeHtml(job.id)}" ${job.status !== "COMPLETED" ? "disabled" : ""} ${selectedJobs.has(job.id) ? "checked" : ""} aria-label="Selecionar ${escapeHtml(job.filename || "arquivo")}"></td>
      <td><div class="filename" title="${escapeHtml(job.filename || "")}">${escapeHtml(job.filename || "")}</div><div class="filemeta">${escapeHtml(meta)}</div></td>
      <td>${progressCell(up)}</td>
      <td>${progressCell(measured, "processing", processingDetail(job))}</td>
      <td><span class="status ${escapeHtml(job.status || "")}">${escapeHtml(statusText(job.status))}</span>${error}</td>
      <td>${job.status === "COMPLETED" ? `<div class="actions"><button class="text-action download" data-job="${escapeHtml(job.id)}" type="button">↓ Baixar TXT</button><button class="text-action preview" data-job="${escapeHtml(job.id)}" type="button">◉ Prévia</button></div>` : `<span class="muted">Aguardando</span>`}</td>`;
    body.appendChild(tr);
  }
  if (!visible.length) body.innerHTML = `<tr><td colspan="6" class="empty">Nenhum arquivo encontrado com os filtros selecionados.</td></tr>`;
  $("tableFeedback").textContent = `${visible.length} arquivo(s) exibido(s) · atualização a cada 3 segundos`;
  updateSelectionControls();
}

function updateSelectionControls() {
  const available = visibleJobs().filter(j => j.status === "COMPLETED");
  $("selectAll").checked = available.length > 0 && available.every(j => selectedJobs.has(j.id));
  $("selectAll").indeterminate = available.some(j => selectedJobs.has(j.id)) && !$("selectAll").checked;
  $("zipBtn").disabled = selectedJobs.size === 0;
  $("zipBtn").textContent = `Baixar selecionados (.zip)${selectedJobs.size ? ` · ${selectedJobs.size}` : ""}`;
}

// Delegação evita recriar listeners a cada atualização de progresso.
$("jobsBody").addEventListener("change", e => {
  const el = e.target.closest(".job-check");
  if (!el) return;
  el.checked ? selectedJobs.add(el.dataset.id) : selectedJobs.delete(el.dataset.id);
  updateSelectionControls();
});

$("jobsBody").addEventListener("click", async e => {
  const element = e.target.closest("button");
  if (!element) return;
  const id = element.dataset.job;
  try {
    if (element.classList.contains("download")) {
      const data = await api(`/jobs/${encodeURIComponent(id)}/download`);
      window.location.href = data.url;
    } else if (element.classList.contains("preview")) {
      $("previewTitle").textContent = "Prévia do TXT";
      $("previewHint").textContent = "Carregando primeiras linhas...";
      $("previewContent").textContent = "";
      $("previewDialog").showModal();
      const data = await api(`/jobs/${encodeURIComponent(id)}/preview`);
      $("previewTitle").textContent = data.filename || "Prévia do TXT";
      $("previewContent").textContent = data.preview || "(Arquivo vazio)";
      $("previewHint").textContent = data.truncated ? "Exibindo apenas os primeiros 16 KB. Baixe o TXT para ver tudo." : "Prévia completa do arquivo.";
    } else if (element.classList.contains("error-detail")) {
      const job = lastJobs.find(j => j.id === element.dataset.error);
      alert(job?.error || "O motivo do erro não foi registrado.");
    }
  } catch (err) {
    if (element.classList.contains("preview")) $("previewDialog").close();
    alert(err.message);
  }
});

$("closePreviewBtn").addEventListener("click", () => $("previewDialog").close());
$("searchInput").addEventListener("input", () => renderJobs(lastJobs));
$("statusFilter").addEventListener("change", () => renderJobs(lastJobs));
$("selectAll").addEventListener("change", e => {
  for (const j of visibleJobs().filter(j => j.status === "COMPLETED")) {
    e.target.checked ? selectedJobs.add(j.id) : selectedJobs.delete(j.id);
  }
  renderJobs(lastJobs);
});
$("clearBtn").addEventListener("click", () => {
  for (const j of lastJobs) if (j.status === "COMPLETED") { hiddenJobs.add(j.id); selectedJobs.delete(j.id); }
  renderJobs(lastJobs);
  $("tableFeedback").textContent = "Concluídos ocultados nesta sessão; os arquivos não foram excluídos do servidor.";
});
$("zipBtn").addEventListener("click", async () => {
  if (!selectedJobs.size) return;
  if (selectedJobs.size > 20) return alert("Selecione no máximo 20 arquivos por ZIP.");
  const btn = $("zipBtn"); btn.disabled = true;
  try {
    const response = await fetch(`${CONFIG.apiBaseUrl}/jobs/download-zip`, {
      method: "POST", headers: {"Authorization": `Bearer ${await token()}`, "Content-Type": "application/json"},
      body: JSON.stringify({job_ids:[...selectedJobs]})
    });
    if (!response.ok) {
      const data = await response.json().catch(() => ({}));
      throw new Error(data.detail || `HTTP ${response.status}`);
    }
    const blob = await response.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a"); a.href = url; a.download = "cognotxt-resultados.zip";
    document.body.appendChild(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 60000);
  } catch (error) { alert(`Erro ao gerar ZIP: ${error.message}`); }
  finally { updateSelectionControls(); }
});

function escapeHtml(s) {
  return String(s).replace(/[&<>'"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c]));
}

async function refreshJobs() {
  if (!auth.currentUser || refreshing) return;
  refreshing = true;
  try {
    const data = await api("/jobs");
    for (const j of data.jobs) if (j.status !== "COMPLETED") selectedJobs.delete(j.id);
    // Depois que o Storage confirma, mantém 100% para jobs em execução.
    for (const j of data.jobs) {
      if (["UPLOADED", "QUEUED", "PROCESSING", "COMPLETED"].includes(j.status)) uploadProgress.delete(j.id);
    }
    renderJobs(data.jobs);
  } catch (e) { console.error(e); }
  finally { refreshing = false; }
}

$("loginForm").addEventListener("submit", async (e) => {
  e.preventDefault(); $("loginError").textContent = "";
  try { await signInWithEmailAndPassword(auth, $("email").value.trim(), $("password").value); }
  catch (err) { $("loginError").textContent = "Não foi possível entrar. Verifique e-mail e senha."; }
});

$("logoutBtn").addEventListener("click", () => signOut(auth));

$("uploadBtn").addEventListener("click", async () => {
  const files = [...$("fileInput").files];
  if (!files.length) return alert("Selecione um ou mais PDFs.");
  $("uploadBtn").disabled = true;
  try {
    for (const file of files) {
      if (file.type !== "application/pdf" && !file.name.toLowerCase().endsWith(".pdf")) continue;
      const session = await api("/uploads/session", {method:"POST", body:JSON.stringify({filename:file.name,size:file.size,content_type:"application/pdf"})});
      uploadProgress.set(session.job_id, 0);
      localFiles.set(session.job_id, {name:file.name, size:file.size});
      renderJobs(lastJobs);
      await uploadResumable(file, session.job_id, session.session_url);
    }
    $("fileInput").value = "";
    await refreshJobs();
  } catch (e) { alert(`Erro no upload: ${e.message}`); }
  finally { $("uploadBtn").disabled = false; }
});

onAuthStateChanged(auth, async (user) => {
  const logged = !!user;
  $("loginView").classList.toggle("hidden", logged);
  $("appView").classList.toggle("hidden", !logged);
  $("logoutBtn").classList.toggle("hidden", !logged);
  if (user) {
    $("userEmail").textContent = user.email || "";
    await refreshJobs();
    clearInterval(refreshTimer);
    refreshTimer = setInterval(refreshJobs, 3000);
  } else {
    clearInterval(refreshTimer); refreshTimer = null;
    selectedJobs.clear(); hiddenJobs.clear(); localFiles.clear(); uploadProgress.clear(); lastJobs = [];
  }
});
