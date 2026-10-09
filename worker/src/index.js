// Relais Telegram -> internbot, hébergé gratuitement sur Cloudflare Workers.
//
// Le bot principal tourne sur GitHub Actions (toutes les 30 min) et n'écoute pas Telegram.
// Ce relais, lui, reçoit les messages en temps réel (webhook Telegram) :
//   /offres [mots]  -> répond tout de suite avec la liste des offres ouvertes (current.json,
//                      mise à jour à chaque passage du bot), éventuellement filtrée par mots ;
//   /refresh        -> déclenche une vraie recherche sur GitHub (--send-all), la liste
//                      complète arrive ~5 min plus tard ;
//   /statut         -> date de la dernière mise à jour ;
//   /status         -> santé de chaque entreprise (dernier succès, offres, NOTIFY/REVIEW,
//                      erreur, entreprises suivies à la main) ;
//   /aide.
//
// Sécurité : seuls les messages venant de TELEGRAM_CHAT_ID sont traités (les autres sont
// ignorés en silence) et Telegram doit présenter WEBHOOK_SECRET à chaque appel.
//
// Secrets (wrangler secret put …) : TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, GITHUB_TOKEN,
// WEBHOOK_SECRET. Variable (wrangler.toml) : GITHUB_REPO.

const TELEGRAM_MAX = 4096;
const MAX_MESSAGES = 15; // au-delà, on invite à filtrer (/offres paris)
const WORKFLOW = "check.yml";

export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);

    if (url.pathname === "/setup") {
      return setup(url, env);
    }
    if (url.pathname !== "/telegram" || request.method !== "POST") {
      return new Response("internbot relay", { status: 404 });
    }
    if (request.headers.get("X-Telegram-Bot-Api-Secret-Token") !== env.WEBHOOK_SECRET) {
      return new Response("forbidden", { status: 403 });
    }

    const update = await request.json().catch(() => null);
    const message = update && update.message;
    if (!message || typeof message.text !== "string") return ok();
    if (String(message.chat && message.chat.id) !== String(env.TELEGRAM_CHAT_ID).trim()) {
      return ok(); // bot privé : on ignore les inconnus sans répondre
    }

    // On répond 200 tout de suite à Telegram ; le travail continue en arrière-plan.
    ctx.waitUntil(
      handleCommand(message.text.trim(), env).catch((err) =>
        sendMessage(env, `⚠️ Erreur du relais : ${escapeHtml(String(err && err.message))}`),
      ),
    );
    return ok();
  },
};

// -- commandes ----------------------------------------------------------------------------------

export async function handleCommand(text, env) {
  const [rawCommand, ...rest] = text.split(/\s+/);
  const command = rawCommand.toLowerCase().replace(/@.*$/, ""); // /offres@MonBot -> /offres
  const args = rest.join(" ");

  switch (command) {
    case "/offres":
    case "/scrap":
    case "/liste":
      return commandOffers(env, args);
    case "/refresh":
      return commandRefresh(env);
    case "/statut":
      return commandStatus(env);
    case "/status":
    case "/sante":
      return commandHealth(env);
    default:
      return sendMessage(env, HELP);
  }
}

const HELP = [
  "🤖 <b>internbot</b>",
  "",
  "/offres — toutes les offres de stage ouvertes qui passent tes filtres",
  "/offres cisco — les offres d'une entreprise",
  "/offres paris — filtrées par mot ou expression entière (titre ou lieu)",
  "⭐ = offre IA, affichée en premier",
  "/refresh — relance une vraie recherche maintenant (~5 min)",
  "/statut — date de la dernière mise à jour",
  "/status — santé de chaque entreprise (erreurs, offres, NOTIFY/REVIEW)",
  "",
  "Les nouvelles offres continuent d'arriver toutes seules, toutes les 30 min.",
].join("\n");

async function commandOffers(env, query) {
  const snapshot = await fetchSnapshot(env);
  if (!snapshot) {
    return sendMessage(
      env,
      "La liste n'existe pas encore : elle est créée au prochain passage du bot. " +
        "Envoie /refresh pour lancer une recherche maintenant.",
    );
  }
  let jobs = flattenSnapshot(snapshot);
  const total = jobs.length;
  // Entreprises connues = celles de la config (current.json en a une entrée par entreprise).
  if (query) jobs = filterJobs(jobs, query, Object.keys(snapshot.companies || {}));
  const subtitle =
    `mise à jour ${formatAge(snapshot.updated_at)}` +
    (query ? ` — filtre « ${query} » : ${jobs.length}/${total}` : "");
  const messages = buildListingMessages(jobs, subtitle);
  const toSend = messages.slice(0, MAX_MESSAGES);
  for (const [i, msg] of toSend.entries()) {
    if (i > 0) await sleep(1100); // ~1 message/s par conversation (limite Telegram)
    await sendMessage(env, msg);
  }
  if (messages.length > MAX_MESSAGES) {
    await sleep(1100);
    await sendMessage(
      env,
      `… liste tronquée (${messages.length} messages). Affine avec un mot : ` +
        "<code>/offres paris</code>, <code>/offres nvidia</code>, <code>/offres remote</code>.",
    );
  }
}

async function commandRefresh(env) {
  const repo = env.GITHUB_REPO;
  const running = await github(env, `/repos/${repo}/actions/workflows/${WORKFLOW}/runs?status=in_progress&per_page=1`);
  const queued = await github(env, `/repos/${repo}/actions/workflows/${WORKFLOW}/runs?status=queued&per_page=1`);
  if ((running.total_count || 0) + (queued.total_count || 0) > 0) {
    return sendMessage(env, "⏳ Une recherche est déjà en cours, la réponse arrive bientôt.");
  }
  await github(env, `/repos/${repo}/actions/workflows/${WORKFLOW}/dispatches`, {
    method: "POST",
    body: JSON.stringify({ ref: "main", inputs: { args: "--send-all" } }),
  });
  return sendMessage(
    env,
    "🔄 Recherche lancée sur toutes les entreprises.\nLa liste complète arrive dans ~5 min.",
  );
}

async function commandStatus(env) {
  const snapshot = await fetchSnapshot(env);
  if (!snapshot) return sendMessage(env, "Pas encore de liste : envoie /refresh.");
  const companies = Object.keys(snapshot.companies || {}).length;
  const jobs = flattenSnapshot(snapshot).length;
  return sendMessage(
    env,
    `📊 ${jobs} offre(s) ouverte(s) chez ${companies} entreprise(s)\n` +
      `Dernière mise à jour : ${formatAge(snapshot.updated_at)}`,
  );
}

async function commandHealth(env) {
  const snapshot = await fetchSnapshot(env);
  if (!snapshot || !snapshot.health) {
    return sendMessage(env, "Pas encore de données de santé : elles arrivent au prochain passage.");
  }
  const messages = buildHealthMessages(snapshot.health, formatAge(snapshot.updated_at));
  for (const [i, msg] of messages.entries()) {
    if (i > 0) await sleep(1100);
    await sendMessage(env, msg);
  }
}

const HEALTH_ORDER = ["error", "ok", "pending", "manual", "disabled"];
const HEALTH_ICON = { error: "❌", ok: "✅", pending: "⏳", manual: "✋", disabled: "⏸" };

// Une ligne par entreprise, erreurs en tête ; découpage à 4096 caractères.
export function buildHealthMessages(health, age, limit = TELEGRAM_MAX) {
  const entries = Object.entries(health || {});
  const counts = {};
  for (const [, h] of entries) counts[h.status] = (counts[h.status] || 0) + 1;
  const summary = HEALTH_ORDER.filter((k) => counts[k])
    .map((k) => `${HEALTH_ICON[k]} ${counts[k]} ${k}`)
    .join(" · ");
  const header = [
    `🩺 <b>Santé : ${entries.length} entreprise(s)</b>`,
    summary,
    `<i>mise à jour ${escapeHtml(age)}</i>`,
    "<i>offres · NOTIFY (notifiées) · REVIEW (stages hors mots-clés métier)</i>",
  ].join("\n");

  entries.sort(
    ([a, ha], [b, hb]) =>
      HEALTH_ORDER.indexOf(ha.status) - HEALTH_ORDER.indexOf(hb.status) || a.localeCompare(b, "fr"),
  );
  const messages = [];
  let current = header;
  let section = null;
  for (const [name, h] of entries) {
    let line = "";
    if (h.status !== section) {
      section = h.status;
      line += `\n\n<b>${HEALTH_ICON[section] || ""} ${escapeHtml(section)}</b>`;
    }
    line += `\n${escapeHtml(name)} <i>(${escapeHtml(h.provider)})</i>`;
    if (h.status === "ok" || (h.status === "error" && h.fetched != null)) {
      line += ` ${h.fetched ?? "-"} · ${h.notify ?? "-"} · ${h.review ?? "-"}`;
    }
    if (h.status === "error") {
      line += `\n   ↳ ${h.failures || 1} échec(s) d'affilée : ${escapeHtml(clip(h.error, 160))}`;
      if (h.last_success) line += ` (dernier succès ${escapeHtml(formatAge(h.last_success))})`;
    }
    if (h.status === "manual" && h.careers_url) {
      line += ` — <a href="${escapeAttr(h.careers_url)}">site</a>`;
    }
    if (current.length + line.length > limit) {
      messages.push(current);
      current = line.replace(/^\n+/, "");
    } else {
      current += line;
    }
  }
  messages.push(current);
  return messages;
}

// -- données ------------------------------------------------------------------------------------

async function fetchSnapshot(env) {
  const res = await fetch(
    `https://api.github.com/repos/${env.GITHUB_REPO}/contents/current.json?ref=state`,
    { headers: githubHeaders(env, "application/vnd.github.raw") },
  );
  if (res.status === 404) return null;
  if (!res.ok) throw new Error(`GitHub ${res.status} en lisant current.json`);
  return res.json();
}

// Offres « notify » et « review » du filtre v3 (current.json ne contient jamais les « drop » ;
// le test sert de garde-fou). Les listes d'avant le v3 n'ont pas de champ status.
export function flattenSnapshot(snapshot) {
  const jobs = [];
  for (const [company, entry] of Object.entries(snapshot.companies || {})) {
    for (const job of entry.jobs || []) {
      if (job.status !== "drop") jobs.push({ company, ...job });
    }
  }
  return jobs;
}

// Portage exact de norm() et matches_query() de src/internbot/filters_v3.py (mêmes cas de
// test des deux côtés) : minuscules, sans accents, ponctuation -> espaces, entouré d'espaces.
export function norm(text) {
  const t = String(text || "")
    .normalize("NFKD")
    .replace(/\p{M}/gu, "")
    .toLowerCase()
    .replace(/[^a-z0-9+#]+/g, " ")
    .trim();
  return ` ${t} `;
}

// Recherche /offres :
// - la requête est un nom d'entreprise connu -> on ne regarde QUE le champ entreprise
//   (« /offres cisco » ne renvoie pas les offres à San Francisco) ;
// - sinon -> mot ou expression entière dans l'entreprise, le titre ou le lieu.
export function matchesQuery(query, company, title, location, knownCompanies) {
  const q = norm(query).trim();
  if (!q) return true;
  const known = new Set([...knownCompanies].map((c) => norm(c).trim()));
  if (known.has(q)) return norm(company).trim() === q;
  return [company, title, location].some((field) => norm(field).includes(` ${q} `));
}

export function filterJobs(jobs, query, knownCompanies) {
  return jobs.filter((job) =>
    matchesQuery(query, job.company, job.title, job.location, knownCompanies),
  );
}

// -- mise en forme (même rendu que build_listing_messages côté Python) ---------------------------

export function escapeHtml(text) {
  return String(text).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

function escapeAttr(text) {
  return escapeHtml(text).replace(/"/g, "&quot;");
}

function clip(text, n) {
  text = String(text || "");
  return text.length <= n ? text : text.slice(0, n - 1) + "…";
}

const STAR = "⭐ "; // offre IA (priorité du filtre v3)

// Offres IA (⭐) d'abord, puis les autres ; groupées par entreprise dans chaque partie.
export function buildListingMessages(jobs, subtitle, limit = TELEGRAM_MAX) {
  let header = `📋 <b>${jobs.length} offre(s) ouverte(s)</b> correspondant à tes filtres`;
  if (subtitle) header += `\n<i>${escapeHtml(subtitle)}</i>`;
  if (jobs.length === 0) return [`${header}\n\nAucune offre ne correspond.`];

  const groups = [];
  for (const priority of [true, false]) {
    const byCompany = new Map();
    for (const job of jobs.filter((j) => Boolean(j.priority) === priority)) {
      if (!byCompany.has(job.company)) byCompany.set(job.company, []);
      byCompany.get(job.company).push(job);
    }
    const companies = [...byCompany.keys()].sort((a, b) => a.localeCompare(b, "fr"));
    for (const company of companies) groups.push([priority, company, byCompany.get(company)]);
  }

  const messages = [];
  let current = header;
  for (const [priority, company, group] of groups) {
    const star = priority ? STAR : "";
    const companyLine = `${star}<b>${escapeHtml(company)}</b> (${group.length})`;
    if (current.length + companyLine.length + 202 > limit) {
      messages.push(current);
      current = companyLine;
    } else {
      current += `\n\n${companyLine}`;
    }
    for (const job of group) {
      let line = `\n• ${star}<a href="${escapeAttr(job.url)}">${escapeHtml(clip(job.title, 150))}</a>`;
      if (job.location) line += ` — ${escapeHtml(clip(job.location, 80))}`;
      if (current.length + line.length > limit) {
        messages.push(current);
        current = `${star}<b>${escapeHtml(company)}</b> (suite)${line}`;
      } else {
        current += line;
      }
    }
  }
  messages.push(current);
  return messages;
}

export function formatAge(iso, now = Date.now()) {
  if (!iso) return "inconnue";
  const minutes = Math.round((now - Date.parse(iso)) / 60000);
  if (minutes < 1) return "à l'instant";
  if (minutes < 60) return `il y a ${minutes} min`;
  const hours = Math.floor(minutes / 60);
  if (hours < 48) return `il y a ${hours} h ${String(minutes % 60).padStart(2, "0")}`;
  return `il y a ${Math.floor(hours / 24)} jours`;
}

// -- API externes -------------------------------------------------------------------------------

function githubHeaders(env, accept = "application/vnd.github+json") {
  return {
    Accept: accept,
    Authorization: `Bearer ${env.GITHUB_TOKEN}`,
    "User-Agent": "internbot-relay",
    "X-GitHub-Api-Version": "2022-11-28",
  };
}

async function github(env, path, init = {}) {
  const res = await fetch(`https://api.github.com${path}`, {
    ...init,
    headers: { ...githubHeaders(env), "Content-Type": "application/json" },
  });
  if (!res.ok) {
    const hint = res.status === 401 || res.status === 403 || res.status === 404
      ? " (GITHUB_TOKEN invalide ou sans les droits Actions/Contents sur le dépôt ?)"
      : "";
    throw new Error(`GitHub ${res.status}${hint}`);
  }
  return res.status === 204 ? {} : res.json();
}

async function telegram(env, method, payload) {
  const res = await fetch(`https://api.telegram.org/bot${env.TELEGRAM_BOT_TOKEN}/${method}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return res.json();
}

export function sendMessage(env, text) {
  return telegram(env, "sendMessage", {
    chat_id: String(env.TELEGRAM_CHAT_ID).trim(),
    text,
    parse_mode: "HTML",
    link_preview_options: { is_disabled: true },
  });
}

// GET /setup?key=WEBHOOK_SECRET : branche le webhook Telegram sur ce relais + menu des commandes.
async function setup(url, env) {
  if (!env.WEBHOOK_SECRET || url.searchParams.get("key") !== env.WEBHOOK_SECRET) {
    return new Response("forbidden", { status: 403 });
  }
  const webhook = await telegram(env, "setWebhook", {
    url: `${url.origin}/telegram`,
    secret_token: env.WEBHOOK_SECRET,
    allowed_updates: ["message"],
    drop_pending_updates: true,
  });
  const commands = await telegram(env, "setMyCommands", {
    commands: [
      { command: "offres", description: "Toutes les offres ouvertes (option : mot-clé)" },
      { command: "refresh", description: "Relancer une recherche maintenant (~5 min)" },
      { command: "statut", description: "Date de la dernière mise à jour" },
      { command: "status", description: "Santé de chaque entreprise" },
      { command: "aide", description: "Aide" },
    ],
  });
  return Response.json({ webhook, commands });
}

function ok() {
  return new Response("ok");
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}
