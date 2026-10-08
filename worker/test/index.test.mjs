// Tests hors-ligne du relais : `node --test worker/test` (fetch est simulé).
import assert from "node:assert/strict";
import { afterEach, beforeEach, test } from "node:test";

import worker, {
  buildHealthMessages,
  buildListingMessages,
  filterJobs,
  flattenSnapshot,
  formatAge,
  handleCommand,
} from "../src/index.js";

const ENV = {
  TELEGRAM_BOT_TOKEN: "123:abc",
  TELEGRAM_CHAT_ID: "42",
  GITHUB_TOKEN: "ghp_test",
  WEBHOOK_SECRET: "s3cret",
  GITHUB_REPO: "me/internship-bot",
};

const SNAPSHOT = {
  version: 1,
  updated_at: new Date(Date.now() - 30 * 60000).toISOString(),
  companies: {
    Datadog: {
      jobs: [
        { job_id: "1", title: "Software Engineering Intern", location: "Paris, France", url: "https://x/1" },
        { job_id: "2", title: "Software Engineering Intern", location: "Madrid, Spain", url: "https://x/2" },
      ],
    },
    Stripe: { jobs: [{ job_id: "3", title: "Software Engineer, Intern", location: "London", url: "https://x/3" }] },
  },
};

let calls;
let routes;

beforeEach(() => {
  calls = [];
  routes = [];
  globalThis.fetch = async (url, init = {}) => {
    calls.push({ url: String(url), init });
    for (const [pattern, handler] of routes) {
      if (String(url).includes(pattern)) return handler(url, init);
    }
    if (String(url).includes("api.telegram.org")) return Response.json({ ok: true });
    return new Response("not found", { status: 404 });
  };
});

afterEach(() => {
  delete globalThis.fetch;
});

const telegramTexts = () =>
  calls.filter((c) => c.url.includes("/sendMessage")).map((c) => JSON.parse(c.init.body).text);

function update(text, chatId = 42) {
  return new Request("https://relay.example/telegram", {
    method: "POST",
    headers: { "X-Telegram-Bot-Api-Secret-Token": "s3cret", "Content-Type": "application/json" },
    body: JSON.stringify({ message: { text, chat: { id: chatId } } }),
  });
}

async function dispatch(request) {
  const pending = [];
  const res = await worker.fetch(request, ENV, { waitUntil: (p) => pending.push(p) });
  await Promise.all(pending);
  return res;
}

test("rejette un appel sans le secret du webhook", async () => {
  const req = new Request("https://relay.example/telegram", { method: "POST", body: "{}" });
  const res = await dispatch(req);
  assert.equal(res.status, 403);
  assert.equal(calls.length, 0);
});

test("ignore en silence les messages d'un autre utilisateur", async () => {
  const res = await dispatch(update("/offres", 999));
  assert.equal(res.status, 200);
  assert.equal(calls.length, 0);
});

test("/offres renvoie la liste depuis current.json (branche state)", async () => {
  routes.push(["contents/current.json?ref=state", () => Response.json(SNAPSHOT)]);
  await dispatch(update("/offres"));
  const ghCall = calls.find((c) => c.url.includes("current.json"));
  assert.equal(ghCall.init.headers.Authorization, "Bearer ghp_test");
  const [text] = telegramTexts();
  assert.match(text, /3 offre\(s\) ouverte\(s\)/);
  assert.match(text, /<b>Datadog<\/b> \(2\)/);
  assert.match(text, /il y a 30 min/);
});

test("/offres paris filtre sans tenir compte des accents ni de la casse", async () => {
  routes.push(["current.json", () => Response.json(SNAPSHOT)]);
  await dispatch(update("/offres PARÍS"));
  const [text] = telegramTexts();
  assert.match(text, /1 offre\(s\)/);
  assert.match(text, /filtre « PARÍS » : 1\/3/);
  assert.doesNotMatch(text, /Madrid/);
});

test("/offres sans liste encore créée", async () => {
  await dispatch(update("/offres"));
  assert.match(telegramTexts()[0], /pas encore/);
});

test("/refresh déclenche le workflow avec --send-all", async () => {
  routes.push(["runs?status=", () => Response.json({ total_count: 0 })]);
  routes.push(["/dispatches", () => new Response(null, { status: 204 })]);
  await dispatch(update("/refresh"));
  const call = calls.find((c) => c.url.includes("/dispatches"));
  assert.equal(call.init.method, "POST");
  assert.deepEqual(JSON.parse(call.init.body), { ref: "main", inputs: { args: "--send-all" } });
  assert.match(telegramTexts()[0], /Recherche lancée/);
});

test("/refresh ne relance pas si une recherche tourne déjà", async () => {
  routes.push(["status=in_progress", () => Response.json({ total_count: 1 })]);
  routes.push(["status=queued", () => Response.json({ total_count: 0 })]);
  await dispatch(update("/refresh"));
  assert.ok(!calls.some((c) => c.url.includes("/dispatches")));
  assert.match(telegramTexts()[0], /déjà en cours/);
});

test("erreur GitHub : message clair renvoyé sur Telegram", async () => {
  routes.push(["runs?status=", () => new Response("bad", { status: 401 })]);
  await dispatch(update("/refresh"));
  assert.match(telegramTexts()[0], /GITHUB_TOKEN invalide/);
});

test("commande inconnue -> aide ; /offres@MonBot reconnu", async () => {
  await handleCommand("bonjour", ENV);
  assert.match(telegramTexts()[0], /\/offres/);
  routes.push(["current.json", () => Response.json(SNAPSHOT)]);
  await handleCommand("/offres@Alertes_bot", ENV);
  assert.match(telegramTexts()[1], /3 offre/);
});

test("/setup exige la clé et branche le webhook avec le secret", async () => {
  let res = await worker.fetch(new Request("https://relay.example/setup?key=nope"), ENV, {});
  assert.equal(res.status, 403);
  res = await worker.fetch(new Request("https://relay.example/setup?key=s3cret"), ENV, {});
  assert.equal(res.status, 200);
  const hook = calls.find((c) => c.url.endsWith("/setWebhook"));
  const body = JSON.parse(hook.init.body);
  assert.equal(body.url, "https://relay.example/telegram");
  assert.equal(body.secret_token, "s3cret");
});

test("découpage : jamais plus de 4096 caractères, en-tête répété (suite)", () => {
  const jobs = Array.from({ length: 300 }, (_, i) => ({
    company: `C${i % 4}`,
    title: `Software Intern ${i} ` + "x".repeat(60),
    location: "Paris <FR>",
    url: `https://x/${i}?a=1&b=2`,
  }));
  const messages = buildListingMessages(jobs, "maj");
  assert.ok(messages.length > 1);
  for (const m of messages) assert.ok(m.length <= 4096, `message de ${m.length} caractères`);
  const lines = messages.join("").match(/• <a href=/g);
  assert.equal(lines.length, 300);
  assert.ok(messages.some((m) => m.includes("(suite)")));
  assert.ok(messages[0].includes("Paris &lt;FR&gt;"));
  assert.ok(messages[0].includes('href="https://x/0?a=1&amp;b=2"'));
});

test("utilitaires", () => {
  assert.equal(flattenSnapshot(SNAPSHOT).length, 3);
  assert.equal(filterJobs(flattenSnapshot(SNAPSHOT), "stripe london").length, 1);
  const now = Date.parse("2026-10-08T12:00:00Z");
  assert.equal(formatAge("2026-10-08T11:58:00Z", now), "il y a 2 min");
  assert.equal(formatAge("2026-10-08T09:30:00Z", now), "il y a 2 h 30");
  assert.equal(formatAge(null, now), "inconnue");
});

test("filtre /offres : début de mot, pas sous-chaîne", () => {
  const jobs = [
    { company: "Adobe", title: "2027 Intern - Software Engineer", location: "San Francisco" },
    { company: "Cisco", title: "Software Engineer Data & AI I (Intern)", location: "San Jose, California, US" },
    { company: "NVIDIA", title: "Deep Learning Intern", location: "Santa Clara" },
    { company: "Datadog", title: "Software Engineering Intern", location: "Paris, France" },
  ];
  const names = (q) => filterJobs(jobs, q).map((j) => j.company);
  assert.deepEqual(names("cisco"), ["Cisco"]); // pas « San Francisco »
  assert.deepEqual(names("Cisco"), ["Cisco"]);
  assert.deepEqual(names("nvid"), ["NVIDIA"]); // préfixe accepté
  assert.deepEqual(names("francisco"), ["Adobe"]);
  assert.deepEqual(names("san jose"), ["Cisco"]);
  assert.deepEqual(names("pâris"), ["Datadog"]); // accents ignorés
  assert.deepEqual(names("ai"), ["Cisco"]); // pas « Paris », « Santa Clara »…
  assert.deepEqual(names("data"), ["Cisco", "Datadog"]);
});

const HEALTH = {
  Adobe: { provider: "workday", status: "ok", last_success: "2026-10-08T11:30:00+00:00", fetched: 120, notify: 4, review: 2, error: null, failures: 0 },
  Broken: { provider: "greenhouse", status: "error", last_success: "2026-10-07T10:00:00+00:00", fetched: 12, notify: 1, review: 0, error: "HTTP 404 <board>", failures: 3 },
  Google: { provider: "manual", status: "manual", reason: "robots.txt", careers_url: "https://g.co/?a=1&b=2", failures: 0 },
  Bosch: { provider: "smartrecruiters", status: "disabled", failures: 0 },
};

test("/status : santé par entreprise, erreurs en tête", async () => {
  routes.push(["current.json", () => Response.json({ ...SNAPSHOT, health: HEALTH })]);
  await dispatch(update("/status"));
  const [text] = telegramTexts();
  assert.match(text, /Santé : 4 entreprise\(s\)/);
  assert.match(text, /❌ 1 error · ✅ 1 ok · ✋ 1 manual · ⏸ 1 disabled/);
  assert.ok(text.indexOf("Broken") < text.indexOf("Adobe"), "erreurs en premier");
  assert.match(text, /Adobe <i>\(workday\)<\/i> 120 · 4 · 2/);
  assert.match(text, /3 échec\(s\) d'affilée : HTTP 404 &lt;board&gt;/);
  assert.match(text, /href="https:\/\/g\.co\/\?a=1&amp;b=2"/);
});

test("/statut reste le résumé court ; /status sans données de santé", async () => {
  routes.push(["current.json", () => Response.json(SNAPSHOT)]);
  await dispatch(update("/statut"));
  await dispatch(update("/status"));
  const [statut, status] = telegramTexts();
  assert.match(statut, /3 offre\(s\) ouverte\(s\)/);
  assert.match(status, /Pas encore de données de santé/);
});

test("santé : découpage à 4096 caractères", () => {
  const health = {};
  for (let i = 0; i < 300; i++) {
    health[`Entreprise ${i}`] = { provider: "workday", status: i % 7 ? "ok" : "error", fetched: 10, notify: 1, review: 0, error: "x".repeat(150), failures: 3 };
  }
  const messages = buildHealthMessages(health, "à l'instant");
  assert.ok(messages.length > 1);
  for (const m of messages) assert.ok(m.length <= 4096);
  assert.equal(messages.join("\n").match(/Entreprise \d+/g).length, 300);
});
