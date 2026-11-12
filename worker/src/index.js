// Homework Lock backend: scan sessions, the phone page, AI checks, rate limits and problem reports.
// Photos and camera frames only live in memory for one request; nothing but the verdict text is stored.
import { MAX_PAGES, PhotoProblem, checkPages, readImage, readPage, reject, sha256 } from "./checker.js";
import { expiredPage, formPage, resultPage } from "./page.js";

const SESSION_TTL_MS = 5 * 60 * 1000;
const MAX_READS = 4 * MAX_PAGES;          // quick page reads per QR code
const MAX_PHOTO_AGE_MS = 24 * 3600 * 1000;
const DAILY_REPORTS = 5;
const PAGE_SIDE = 1568, READ_SIDE = 1024; // image sizes the phone sends (the API's useful maximum)

const json = (obj, status = 200) => Response.json(obj, { status });
const html = (body, status = 200) => new Response(body, { status, headers: { "content-type": "text/html; charset=utf-8" } });
const today = () => new Date().toISOString().slice(0, 10);
const validInstall = (id) => typeof id === "string" && /^[A-Za-z0-9_-]{16,64}$/.test(id);

function newToken() {
  const b = crypto.getRandomValues(new Uint8Array(16));
  return btoa(String.fromCharCode(...b)).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

/** Count one more use of `column` today; false (and nothing counted) once `limit` is reached. */
async function bump(env, install, column, limit) {
  const day = today();
  await env.DB.prepare("INSERT INTO usage (install, day) VALUES (?, ?) ON CONFLICT DO NOTHING").bind(install, day).run();
  const r = await env.DB.prepare(`UPDATE usage SET ${column} = ${column} + 1 WHERE install = ? AND day = ? AND ${column} < ?`)
    .bind(install, day, limit).run();
  return r.meta.changes === 1;
}

async function liveSession(env, token) {
  const s = await env.DB.prepare("SELECT * FROM sessions WHERE token = ?").bind(token).first();
  return s && s.status === "open" && Date.now() - s.created < SESSION_TTL_MS ? s : null;
}

/** Repeat-photo checks, limits, then the AI check. images: [{bytes, type}]. */
async function runCheck(env, install, images, note, checkAnswers) {
  const shas = await Promise.all(images.map((img) => sha256(img.bytes)));
  for (let i = 0; i < shas.length; i++) {
    for (let j = i + 1; j < shas.length; j++) {
      if (shas[i] === shas[j]) return reject(`Pages ${i + 1} and ${j + 1} are the same photo. Take a photo of each different page.`);
    }
  }
  const used = await env.DB.prepare(`SELECT sha FROM used_images WHERE install = ? AND sha IN (${shas.map(() => "?").join(",")})`)
    .bind(install, ...shas).all();
  if (used.results.length) {
    const i = shas.indexOf(used.results[0].sha) + 1;
    return reject(`The photo of page ${i} was already used before. Take new photos.`);
  }
  const total = await env.DB.prepare("SELECT COALESCE(SUM(checks), 0) AS n FROM usage WHERE day = ?").bind(today()).first();
  if (total.n >= Number(env.GLOBAL_DAILY_CHECKS)) {
    return reject("The checking service is very busy today. Try again tomorrow, or ask a parent to unlock.");
  }
  if (!(await bump(env, install, "checks", Number(env.DAILY_CHECKS)))) {
    return reject(`You've used today's ${env.DAILY_CHECKS} homework checks. Try again tomorrow, or ask a parent to unlock.`);
  }
  let result;
  try {
    result = await checkPages(env, images, note, checkAnswers);
  } catch (e) {
    // The service failed, not the student: give the check back.
    await env.DB.prepare("UPDATE usage SET checks = checks - 1 WHERE install = ? AND day = ?").bind(install, today()).run();
    throw e;
  }
  // Every photo that got a verdict is remembered (as a hash only) so the same file can't be reused.
  await env.DB.batch(shas.map((sha) => env.DB.prepare("INSERT OR IGNORE INTO used_images (install, sha) VALUES (?, ?)").bind(install, sha)));
  return result;
}

const problemsOf = (result) => (result.pages || []).filter((p) => !p.complete && p.issue).map((p) => `Page ${p.page}: ${p.issue}`);

async function readPhotos(form, { checkAge }) {
  const files = form.getAll("photo").filter((f) => f instanceof File && f.size);
  if (!files.length) throw new PhotoProblem("No photos arrived. Add a photo of every page.");
  if (files.length > MAX_PAGES) throw new PhotoProblem(`Homework can have 1 to ${MAX_PAGES} pages.`);
  if (checkAge) {
    form.getAll("taken").forEach((taken, i) => {
      const t = Number(taken);
      if (taken && Number.isFinite(t) && Date.now() - t > MAX_PHOTO_AGE_MS) {
        throw new PhotoProblem(`The photo for page ${i + 1} is more than a day old. Use a new photo of today's homework.`);
      }
    });
  }
  return Promise.all(files.map((f, i) => readImage(f, `page ${i + 1}`)));
}

// ---------- phone page ----------
async function phoneSubmit(env, token, request) {
  const s = await liveSession(env, token);
  if (!s) return html(expiredPage(), 410);
  let images, note;
  try {
    const form = await request.formData();
    images = await readPhotos(form, { checkAge: true });
    note = String(form.get("note") || "").trim().slice(0, 300);
  } catch (e) {
    const reason = e instanceof PhotoProblem ? e.message : "The photos didn't upload properly. Try again.";
    return html(resultPage({ approved: false, reason, retry: true }), 400);
  }
  const claimed = await env.DB.prepare("UPDATE sessions SET status = 'checking' WHERE token = ? AND status = 'open'").bind(token).run();
  if (claimed.meta.changes !== 1) return html(expiredPage(), 410);
  let result;
  try {
    result = await runCheck(env, s.install, images, note, Boolean(s.check_answers));
  } catch (e) {
    result = reject(`Could not check the photos: ${e.message}`);
  } finally {
    images.length = 0; // drop the photos right after the decision
  }
  await env.DB.prepare("UPDATE sessions SET status = 'done', result = ? WHERE token = ?").bind(JSON.stringify(result), token).run();
  return html(resultPage({ approved: result.approved, reason: result.reason, problems: problemsOf(result) }));
}

async function phoneRead(env, token, request) {
  const s = await liveSession(env, token);
  if (!s) return json({ message: "This link expired. Show a new QR code on the computer." }, 410);
  const counted = await env.DB.prepare("UPDATE sessions SET reads = reads + 1 WHERE token = ? AND reads < ?").bind(token, MAX_READS).run();
  if (counted.meta.changes !== 1) {
    return json({ message: "Too many tries on this link. Tap Done to check the pages you have, or show a new QR code on the computer." }, 429);
  }
  try {
    const form = await request.formData();
    const frame = form.get("photo"), prev = form.get("prev");
    if (!(frame instanceof File)) return json({ message: "No camera picture arrived." }, 400);
    return json(await readPage(env, await readImage(frame, "this page"), prev instanceof File ? await readImage(prev, "the last page") : null));
  } catch (e) {
    return json({ message: `Couldn't read the page: ${e.message}` }, 502);
  }
}

// ---------- PC app API ----------
async function createSession(env, request, origin) {
  const body = await request.json().catch(() => ({}));
  if (!validInstall(body.install)) return json({ error: "Bad install ID." }, 400);
  if (!(await bump(env, body.install, "sessions", Number(env.DAILY_SESSIONS)))) {
    return json({ error: "Too many QR codes today. Try again tomorrow." }, 429);
  }
  await env.DB.prepare("DELETE FROM sessions WHERE created < ?").bind(Date.now() - 24 * 3600 * 1000).run();
  const token = newToken();
  await env.DB.prepare("INSERT INTO sessions (token, install, created, allow_uploads, check_answers) VALUES (?, ?, ?, ?, ?)")
    .bind(token, body.install, Date.now(), body.allow_uploads === false ? 0 : 1, body.check_answers === true ? 1 : 0).run();
  return json({ token, url: `${origin}/s/${token}`, expires_in: SESSION_TTL_MS / 1000 });
}

async function sessionStatus(env, token, install) {
  const s = await env.DB.prepare("SELECT * FROM sessions WHERE token = ?").bind(token).first();
  if (!s || s.install !== install) return json({ status: "expired" }, 404);
  if (s.status === "done") return json({ status: "done", result: JSON.parse(s.result) });
  if (s.status === "checking") return json({ status: "checking" });
  return json({ status: Date.now() - s.created < SESSION_TTL_MS ? "open" : "expired" });
}

async function pcCheck(env, request) {
  let form, images;
  try {
    form = await request.formData();
  } catch {
    return json({ error: "Bad upload." }, 400);
  }
  const install = form.get("install");
  if (!validInstall(install)) return json({ error: "Bad install ID." }, 400);
  try {
    images = await readPhotos(form, { checkAge: false }); // the app checks file dates itself
  } catch (e) {
    return json(reject(e instanceof PhotoProblem ? e.message : "The photos didn't upload properly."));
  }
  try {
    return json(await runCheck(env, install, images, "", form.get("check_answers") === "1"));
  } catch (e) {
    return json(reject(`Could not check the photos: ${e.message}`));
  } finally {
    images.length = 0;
  }
}

async function report(env, request) {
  const body = await request.json().catch(() => ({}));
  if (!validInstall(body.install)) return json({ error: "Bad install ID." }, 400);
  const description = String(body.description || "").trim().slice(0, 1500);
  if (!description) return json({ error: "Describe the problem first." }, 400);
  if (!env.DISCORD_WEBHOOK) return json({ error: "Reports aren't set up yet." }, 503);
  if (!(await bump(env, body.install, "reports", DAILY_REPORTS))) return json({ error: "Too many reports today." }, 429);
  const version = String(body.version || "?").slice(0, 20);
  const fd = new FormData();
  fd.append("payload_json", JSON.stringify({
    content: `**Problem report** · v${version} · install ${body.install.slice(0, 8)}\n${description}`,
    allowed_mentions: { parse: [] },
  }));
  fd.append("files[0]", new Blob([String(body.log || "").slice(0, 20000)], { type: "text/plain" }), "log.txt");
  const r = await fetch(env.DISCORD_WEBHOOK, { method: "POST", body: fd });
  if (!r.ok) {
    console.error("Discord webhook failed", r.status, await r.text());
    return json({ error: "Couldn't send the report. Try again later." }, 502);
  }
  return json({ ok: true });
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const p = url.pathname, m = request.method;
    let match;
    if ((match = p.match(/^\/s\/([\w-]+)$/))) {
      if (m === "GET") {
        const s = await liveSession(env, match[1]);
        return s ? html(formPage({ allowUploads: Boolean(s.allow_uploads), maxPages: MAX_PAGES, pageSide: PAGE_SIDE, readSide: READ_SIDE }))
                 : html(expiredPage(), 410);
      }
      if (m === "POST") return phoneSubmit(env, match[1], request);
    }
    if ((match = p.match(/^\/s\/([\w-]+)\/read$/)) && m === "POST") return phoneRead(env, match[1], request);
    if (p === "/api/session" && m === "POST") return createSession(env, request, url.origin);
    if ((match = p.match(/^\/api\/session\/([\w-]+)$/)) && m === "GET") return sessionStatus(env, match[1], url.searchParams.get("install"));
    if (p === "/api/check" && m === "POST") return pcCheck(env, request);
    if (p === "/api/report" && m === "POST") return report(env, request);
    if (p === "/") return new Response("Homework Lock is running.");
    return new Response("Not found", { status: 404 });
  },
};
