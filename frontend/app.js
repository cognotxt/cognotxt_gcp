import { initializeApp } from "https://www.gstatic.com/firebasejs/13.0.0/firebase-app.js";
import { getAuth, signInWithEmailAndPassword, signOut, onAuthStateChanged } from "https://www.gstatic.com/firebasejs/13.0.0/firebase-auth.js";
import { CONFIG } from "./config.js";

const firebaseApp = initializeApp(CONFIG.firebase);
const auth = getAuth(firebaseApp);
const $ = (id) => document.getElementById(id);
const uploadProgress = new Map();
let refreshTimer = null;

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
        renderJobs(window.lastJobs || []);
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

function progressCell(value, klass="") {
  const pct = Math.max(0, Math.min(100, Number(value || 0)));
  return `<div class="bar ${klass}"><span style="width:${pct}%"></span></div><div class="pct">${pct}%</div>`;
}

function statusText(status) {
  return ({UPLOADING:"Enviando",QUEUED:"Na fila",PROCESSING:"Processando",COMPLETED:"Pronto",ERROR:"Erro"})[status] || status || "Criado";
}

function renderJobs(jobs) {
  const body = $("jobsBody");
  body.innerHTML = "";
  const byId = new Map(jobs.map(j => [j.id, j]));
  for (const [jobId, pct] of uploadProgress) {
    if (!byId.has(jobId)) byId.set(jobId, {id:jobId, filename:"Upload em andamento", status:"UPLOADING", upload_progress:pct, processing_progress:0});
  }
  const values = [...byId.values()];
  for (const job of values) {
    const tr = document.createElement("tr");
    const up = uploadProgress.has(job.id) ? uploadProgress.get(job.id) : (job.upload_progress || 0);
    tr.innerHTML = `
      <td>${escapeHtml(job.filename || "")}</td>
      <td>${progressCell(up)}</td>
      <td>${progressCell(job.processing_progress || 0, "processing")}</td>
      <td><span class="status ${job.status || ""}" title="${escapeHtml(job.error || "")}">${escapeHtml(statusText(job.status))}</span></td>
      <td>${job.status === "COMPLETED" ? `<a class="download" data-job="${job.id}">Baixar TXT</a>` : "-"}</td>`;
    body.appendChild(tr);
  }
  document.querySelectorAll(".download").forEach(a => a.addEventListener("click", async () => {
    try {
      const data = await api(`/jobs/${a.dataset.job}/download`);
      window.location.href = data.url;
    } catch (e) { alert(e.message); }
  }));
}

function escapeHtml(s) {
  return String(s).replace(/[&<>'"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c]));
}

async function refreshJobs() {
  if (!auth.currentUser) return;
  try {
    const data = await api("/jobs");
    window.lastJobs = data.jobs;
    for (const j of data.jobs) if (j.upload_progress === 100) uploadProgress.delete(j.id);
    renderJobs(data.jobs);
  } catch (e) { console.error(e); }
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
      renderJobs(window.lastJobs || []);
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
  }
});
