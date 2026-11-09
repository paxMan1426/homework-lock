// The phone page: live camera scan of every page (or photos), then the verdict.
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);

const STYLE = `
  :root { --bg:#f6f7f9; --card:#fff; --text:#1b1d21; --muted:#5f6670; --accent:#3b6ff5;
          --ok:#1d8a4a; --bad:#c23b33; --border:#dde1e6; --soft:#eef1f6; }
  @media (prefers-color-scheme: dark) {
    :root { --bg:#121417; --card:#1c1f24; --text:#eceef1; --muted:#9aa2ad; --accent:#6b9bff;
            --ok:#4cc27e; --bad:#ff7a70; --border:#2c3037; --soft:#252a33; }
  }
  * { box-sizing: border-box; }
  body { margin:0; background:var(--bg); color:var(--text);
         font:17px/1.45 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif; }
  main { max-width:480px; margin:0 auto; padding:24px 16px 40px; }
  .card { background:var(--card); border:1px solid var(--border); border-radius:14px; padding:20px; }
  h1 { font-size:1.35rem; margin:0 0 4px; }
  p { color:var(--muted); margin:0 0 18px; }
  .title { display:block; font-weight:600; margin:18px 0 8px; }
  .remove { position:absolute; right:6px; top:6px; width:26px; height:26px; margin:0; padding:0;
            border-radius:99px; background:rgba(0,0,0,.6); color:#fff; font-size:1rem; line-height:26px; }
  .slots { display:grid; grid-template-columns:1fr 1fr; gap:10px; }
  .slot { border:2px dashed var(--border); border-radius:12px; overflow:hidden; display:flex; flex-direction:column; }
  .slot.done { border-style:solid; border-color:var(--accent); }
  .preview { position:relative; height:110px; display:flex; align-items:center; justify-content:center;
             color:var(--muted); font-size:.85rem; }
  .preview img { width:100%; height:100%; object-fit:cover; display:block; }
  .tag { position:absolute; left:6px; top:6px; background:var(--accent); color:#fff; font-size:.75rem;
         padding:2px 8px; border-radius:99px; }
  .actions { display:flex; border-top:1px solid var(--border); }
  .actions label { flex:1; text-align:center; padding:9px 4px; font-size:.85rem; font-weight:600;
                   color:var(--accent); cursor:pointer; }
  .actions label + label { border-left:1px solid var(--border); }
  .bulk { display:block; text-align:center; margin-top:10px; padding:11px; border-radius:12px;
          background:var(--soft); color:var(--accent); font-weight:600; cursor:pointer; }
  input[type=file] { position:absolute; left:-9999px; }
  textarea { width:100%; min-height:70px; padding:10px; font:inherit; color:var(--text);
             background:var(--bg); border:1px solid var(--border); border-radius:10px; }
  button { width:100%; margin-top:18px; padding:14px; font:inherit; font-weight:600; border:0;
           border-radius:12px; background:var(--accent); color:#fff; }
  button:disabled { opacity:.5; }
  .ok { color:var(--ok); } .bad { color:var(--bad); }
  ul { margin:0 0 16px; padding-left:20px; } li { margin:4px 0; }
  .err { color:var(--bad); margin-top:12px; }
  .cam { position:relative; border-radius:12px; overflow:hidden; background:#000; aspect-ratio:3/4; }
  .cam video { width:100%; height:100%; object-fit:cover; display:block; }
  .status { position:absolute; left:0; right:0; bottom:0; padding:12px 14px; background:rgba(0,0,0,.7);
            color:#fff; font-weight:600; text-align:center; }
  .status.ok { background:rgba(29,138,74,.92); } .status.bad { background:rgba(194,59,51,.92); }
  .thumbs { display:flex; gap:8px; overflow-x:auto; margin-top:12px; }
  .thumb { position:relative; flex:0 0 64px; height:84px; border-radius:8px; overflow:hidden;
           border:2px solid var(--accent); }
  .thumb img { width:100%; height:100%; object-fit:cover; display:block; }
  .thumb .tag { left:3px; top:auto; bottom:3px; padding:1px 6px; }
  .thumb .remove { right:3px; top:3px; width:22px; height:22px; line-height:22px; }
  .alt { display:block; text-align:center; margin-top:14px; color:var(--accent); font-weight:600; }`;

const wrap = (body) => `<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="light dark"><title>Homework Lock</title><style>${STYLE}</style></head>
<body><main><div class="card">${body}</div></main></body></html>`;

export function resultPage({ approved, reason, problems = [], retry = false }) {
  if (approved) {
    return wrap(`<h1 class="ok">Approved</h1><p>${esc(reason)}</p><p>Your apps are unlocked on the computer.</p>`);
  }
  return wrap(`<h1 class="bad">Not approved</h1><p>${esc(reason)}</p>` +
    (problems.length ? `<ul>${problems.map((p) => `<li>${esc(p)}</li>`).join("")}</ul>` : "") +
    (retry ? `<p><a href="" style="color:var(--accent);font-weight:600">Go back and fix it</a></p>`
           : `<p>Get a new QR code on the computer to try again.</p>`));
}

export const expiredPage = () => wrap(`<h1 class="bad">Link expired</h1>
  <p>This link was already used or is more than 5 minutes old. Show a new QR code on the computer.</p>`);

export function formPage({ allowUploads, maxPages, pageSide, readSide }) {
  return wrap(`
  <div id="scan" hidden>
    <h1>Scan every page</h1>
    <p>Point the camera at page 1 and hold still. Once a page has been read, you'll be told to flip to the next
       one. Tap the picture to read a page right away.</p>
    <div class="cam" id="cam"><video id="video" playsinline muted autoplay></video>
      <div class="status" id="status">Starting the camera...</div></div>
    <div class="thumbs" id="thumbs"></div>
    <button id="done" type="button" disabled>Point the camera at page 1</button>
    <div class="err" id="scan-err"></div>
    <a class="alt" href="#" id="to-photos">Take photos instead</a>
  </div>
  <div id="photos">
  <h1>Show every page</h1>
  <p>${allowUploads ? "Take or upload a clear photo of each page" : "Take a clear photo of each page"}
     of your finished homework, in order. All pages are needed to unlock. A new page slot appears after
     each photo, and missing pages are spotted automatically.</p>
  <form id="f">
    <span class="title">Pages</span>
    <div class="slots" id="slots"></div>
    ${allowUploads ? `<label class="bulk">Upload several pages at once
      <input id="bulk" type="file" accept="image/*" multiple></label>` : ""}
    <button id="send" type="submit" disabled>Add a photo of page 1</button>
    <div class="err" id="err"></div>
  </form>
  <a class="alt" href="#" id="to-scan" hidden>Scan with the live camera instead</a>
  </div>
  <label class="title" for="note">What did you work on? <span style="font-weight:400;color:var(--muted)">(optional)</span></label>
  <textarea id="note" maxlength="300" placeholder="e.g. Math worksheet, problems 1-40"></textarea>
  <script>
  (function () {
    const MAX = ${maxPages}, UPLOADS = ${allowUploads ? "true" : "false"};
    const slots = document.getElementById('slots'), send = document.getElementById('send');
    const files = [];  // files[i] = photo for page i+1; there's always one empty slot after them

    function makeSlot(i) {
      const f = files[i];
      const s = document.createElement('div'); s.className = 'slot' + (f ? ' done' : '');
      s.innerHTML = '<div class="preview"><span class="tag">Page ' + (i + 1) + '</span>' +
        (f ? '<button type="button" class="remove" aria-label="Remove page ' + (i + 1) + '">&times;</button>'
           : (i === 0 ? 'No photo yet' : 'Next page?')) + '</div>' +
        '<div class="actions">' +
        '<label><span>' + (f ? 'Retake' : 'Camera') + '</span><input type="file" accept="image/*" capture="environment"></label>' +
        (UPLOADS ? '<label><span>' + (f ? 'Replace' : 'Upload') + '</span><input type="file" accept="image/*"></label>' : '') +
        '</div>';
      if (f) {
        const img = document.createElement('img'); img.src = URL.createObjectURL(f);
        s.querySelector('.preview').prepend(img);
        s.querySelector('.remove').onclick = () => { files.splice(i, 1); update(); };
      }
      s.querySelectorAll('input').forEach(inp => inp.addEventListener('change', () => {
        if (inp.files[0]) { files[i] = inp.files[0]; document.getElementById('err').textContent = ''; update(); }
        inp.value = '';
      }));
      return s;
    }
    function update() {
      slots.innerHTML = '';
      const shown = Math.min(files.length + 1, MAX);
      for (let i = 0; i < shown; i++) slots.appendChild(makeSlot(i));
      const n = files.length;
      send.disabled = n === 0;
      send.textContent = n === 0 ? 'Add a photo of page 1' : 'Submit ' + n + (n === 1 ? ' page' : ' pages');
    }
    const bulk = document.getElementById('bulk');
    if (bulk) bulk.addEventListener('change', () => {
      let skipped = 0;
      for (const f of bulk.files) { if (files.length < MAX) files.push(f); else skipped++; }
      bulk.value = '';
      update();
      document.getElementById('err').textContent = skipped ? 'Only ' + MAX + ' pages fit; ' + skipped + ' photo(s) were left out.' : '';
    });
    update();

    // Shrink photos on the phone before sending, so uploads are fast.
    function shrink(file) {
      return new Promise(resolve => {
        const img = new Image();
        img.onload = () => {
          const s = Math.min(1, ${pageSide} / Math.max(img.naturalWidth, img.naturalHeight));
          const c = document.createElement('canvas');
          c.width = Math.round(img.naturalWidth * s); c.height = Math.round(img.naturalHeight * s);
          c.getContext('2d').drawImage(img, 0, 0, c.width, c.height);
          c.toBlob(b => resolve(b || file), 'image/jpeg', 0.85);
        };
        img.onerror = () => resolve(file);
        img.src = URL.createObjectURL(file);
      });
    }
    // Sends every page for the full check. Returns why it failed (the pages are kept), or shows the verdict.
    async function submit(blobs, taken) {
      const fd = new FormData();
      fd.append('note', document.getElementById('note').value);
      blobs.forEach((b, i) => { fd.append('photo', b, 'page' + (i + 1) + '.jpg'); fd.append('taken', taken[i] || ''); });
      try {
        const r = await fetch(location.href, { method: 'POST', body: fd });
        const html = await r.text();
        if (r.status === 400 || r.status === 413) {   // fixable: keep the photos and show why
          const p = new DOMParser().parseFromString(html, 'text/html').querySelector('p');
          return p ? p.textContent : 'Something was wrong with the photos.';
        }
        document.open(); document.write(html); document.close();
        return null;
      } catch (err) {
        return 'Upload failed. Check the internet connection and try again.';
      }
    }
    document.getElementById('f').addEventListener('submit', async e => {
      e.preventDefault();
      const count = files.length;
      send.disabled = true; send.textContent = 'Checking ' + count + (count === 1 ? ' page...' : ' pages...');
      const blobs = [];
      for (let i = 0; i < count; i++) blobs.push(await shrink(files[i]));
      const err = await submit(blobs, files.map(f => f.lastModified || ''));
      if (err) { document.getElementById('err').textContent = err; update(); }
    });

    // ---- Live scan: hold a page still, it gets read, then flip to the next one ----
    const STILL = 7, MOVED = 18, STEADY_TICKS = 3;  // average brightness change per 120 ms tick, out of 255
    const TICK_MS = 120, PAGE_SIDE = ${pageSide}, READ_SIDE = ${readSide};
    const $ = id => document.getElementById(id);
    const video = $('video'), statusEl = $('status'), thumbs = $('thumbs'), done = $('done');
    const pages = [];  // {blob, small, url, label}
    let stream = null, timer = null, state = 'aim', still = 0, prevSmall = null, busy = false, waitUntil = 0;
    const small = document.createElement('canvas');

    function say(text, kind) { statusEl.textContent = text; statusEl.className = 'status' + (kind ? ' ' + kind : ''); }
    function showScan(on) {
      $('scan').hidden = !on; $('photos').hidden = on;
      if (on) startCamera(); else stopCamera();
    }
    async function startCamera() {
      if (stream) return;
      try {
        stream = await navigator.mediaDevices.getUserMedia(
          { video: { facingMode: { ideal: 'environment' }, width: { ideal: 1920 }, height: { ideal: 1080 } }, audio: false });
      } catch (e) {
        showScan(false);
        $('err').textContent = "The camera didn't start" +
          (e && e.name === 'NotAllowedError' ? ' (camera access was blocked)' : '') + '. Take photos instead.';
        return;
      }
      video.srcObject = stream;
      video.play().catch(() => {});
      prevSmall = null; still = 0;
      state = pages.length >= MAX ? 'full' : 'aim';
      say(pages.length >= MAX ? 'That is the most pages. Tap Done.' :
          pages.length ? 'Show page ' + (pages.length + 1) + ' and hold still' : 'Point the camera at page 1 and hold still');
      timer = setInterval(tick, TICK_MS);
    }
    function stopCamera() {
      clearInterval(timer); timer = null;
      if (stream) stream.getTracks().forEach(t => t.stop());
      stream = null;
    }
    // Tiny grayscale copy of the frame: how much it changed since the last tick, and how bright it is.
    function measure() {
      const w = 64, h = Math.max(1, Math.round(w * video.videoHeight / video.videoWidth));
      small.width = w; small.height = h;
      const ctx = small.getContext('2d', { willReadFrequently: true });
      ctx.drawImage(video, 0, 0, w, h);
      const d = ctx.getImageData(0, 0, w, h).data, g = new Float32Array(w * h);
      let sum = 0, motion = 255;
      for (let i = 0; i < g.length; i++) { g[i] = d[i * 4] * .3 + d[i * 4 + 1] * .59 + d[i * 4 + 2] * .11; sum += g[i]; }
      if (prevSmall && prevSmall.length === g.length) {
        motion = 0;
        for (let i = 0; i < g.length; i++) motion += Math.abs(g[i] - prevSmall[i]);
        motion /= g.length;
      }
      prevSmall = g;
      return { motion, bright: sum / g.length };
    }
    function tick() {
      if (busy || !video.videoWidth) return;
      const m = measure();
      if (state === 'flip') {          // don't read again until the page has been turned
        if (m.motion > MOVED) { state = 'aim'; still = 0; say('Hold page ' + (pages.length + 1) + ' still...'); }
        return;
      }
      if (state !== 'aim') return;
      still = m.motion < STILL && m.bright > 35 ? still + 1 : 0;
      if (still >= STEADY_TICKS && Date.now() >= waitUntil) read();
    }
    function toBlob(src, side) {
      const w = src.videoWidth || src.width, h = src.videoHeight || src.height;
      const s = Math.min(1, side / Math.max(w, h));
      const c = document.createElement('canvas');
      c.width = Math.round(w * s); c.height = Math.round(h * s);
      c.getContext('2d').drawImage(src, 0, 0, c.width, c.height);
      return new Promise(resolve => c.toBlob(b => resolve({ blob: b, canvas: c }), 'image/jpeg', 0.85));
    }
    // One frame: a full-size copy kept for the final check, and a small one sent for the quick read.
    async function grab() {
      const full = await toBlob(video, PAGE_SIDE);
      const small = await toBlob(full.canvas, READ_SIDE);
      return { blob: full.blob, small: small.blob };
    }
    async function read() {
      if (busy || !stream || state === 'full' || state === 'stopped') return;
      busy = true; still = 0;
      say('Reading page ' + (pages.length + 1) + '...');
      try {
        const { blob, small: readBlob } = await grab();
        const fd = new FormData();
        fd.append('photo', readBlob, 'frame.jpg');
        if (pages.length) fd.append('prev', pages[pages.length - 1].small, 'prev.jpg');
        const r = await fetch(location.pathname + '/read', { method: 'POST', body: fd });
        const a = await r.json().catch(() => ({}));
        if (r.status === 410) { location.reload(); return; }
        if (r.status === 429) { state = 'stopped'; say(a.message || 'Too many tries.', 'bad'); return; }
        if (!r.ok) { say(a.message || "Couldn't read the page. Hold still.", 'bad'); waitUntil = Date.now() + 3000; return; }
        if (a.ok) {
          addPage(blob, readBlob, a.label);
          if (navigator.vibrate) navigator.vibrate(80);
          if (pages.length >= MAX) { state = 'full'; say('Got page ' + pages.length + '. That is the most pages. Tap Done.', 'ok'); }
          else { state = 'flip'; say('Got page ' + pages.length + (a.label ? ': ' + a.label : '') +
                                     '. Flip to the next page, or tap Done if that was the last.', 'ok'); }
        } else if (a.same) {
          state = 'flip';
          say("That's still page " + pages.length + '. Flip to the next page, or tap Done.');
        } else {
          say((a.tip || "Couldn't read that") + '. Hold page ' + (pages.length + 1) + ' still.', 'bad');
          waitUntil = Date.now() + 700;
        }
      } catch (e) {
        say('Lost the connection. Check the internet.', 'bad'); waitUntil = Date.now() + 3000;
      } finally {
        busy = false; still = 0;
      }
    }
    function addPage(blob, small, label) {
      pages.push({ blob, small, url: URL.createObjectURL(small), label: label || '' });
      drawPages();
    }
    function drawPages() {
      thumbs.innerHTML = '';
      pages.forEach((p, i) => {
        const t = document.createElement('div'); t.className = 'thumb'; t.title = p.label;
        t.innerHTML = '<img alt=""><span class="tag">' + (i + 1) + '</span>' +
                      '<button type="button" class="remove" aria-label="Remove page ' + (i + 1) + '">&times;</button>';
        t.querySelector('img').src = p.url;
        t.querySelector('.remove').onclick = () => {
          URL.revokeObjectURL(p.url); pages.splice(i, 1); drawPages();
          if (state === 'full' || state === 'flip') state = 'aim';
          if (stream) say('Show page ' + (pages.length + 1) + ' and hold still');
        };
        thumbs.appendChild(t);
      });
      const n = pages.length;
      done.disabled = n === 0;
      done.textContent = n === 0 ? 'Point the camera at page 1' : 'Done - check ' + n + (n === 1 ? ' page' : ' pages');
    }
    $('cam').addEventListener('click', () => { if (state === 'flip' || state === 'aim') { state = 'aim'; read(); } });
    done.addEventListener('click', async () => {
      const n = pages.length;
      stopCamera();
      done.disabled = true; done.textContent = 'Checking ' + n + (n === 1 ? ' page...' : ' pages...');
      const now = Date.now();
      const err = await submit(pages.map(p => p.blob), pages.map(() => now));
      if (err) { $('scan-err').textContent = err; drawPages(); startCamera(); }
    });
    if (window.isSecureContext && navigator.mediaDevices && navigator.mediaDevices.getUserMedia) {
      $('to-photos').onclick = e => { e.preventDefault(); showScan(false); };
      $('to-scan').hidden = false;
      $('to-scan').onclick = e => { e.preventDefault(); $('err').textContent = ''; showScan(true); };
      showScan(true);
    }
  })();
  </script>`);
}
