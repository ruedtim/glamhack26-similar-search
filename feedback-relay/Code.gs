/**
 * Feedback relay for the GLAMhack 2026 pages: one Google Apps Script web app for several sites.
 *   box-viewer      Provenance Pursuit results        (ruedtim/glamhack26-box-viewer)
 *   similar-search  Ähnlichkeitssuche «To Be Renamed!» (ruedtim/glamhack26-similar-search)
 *
 * The feedback form of each site (feedback.js) posts here with its `site`, and the relay keeps each message for up to
 * KEEP_HOURS. The GitHub Action .github/workflows/feedback.yml of each repository fetches its own new messages
 * (?pending=1&site=<site>), opens one issue each with GitHub's own token and then removes the message (?done=<id>).
 * So no personal token is stored anywhere, and visitors need no GitHub account.
 * A post or pickup without `site` (the first version of the box viewer's form and Action) counts as box-viewer.
 *
 * Endpoints: POST stores a message; GET ?pending=1&site=<site> lists that site's waiting messages (they become public
 * issues anyway); GET ?done=<id> removes one once its issue exists; GET alone shows per site how many messages wait
 * and how old the oldest is (a large age means the site's Action has not run).
 * Deploy: Deploy → New deployment → Web app; Execute as: Me; Who has access: Anyone.
 * Pause without redeploying (Project settings → Script properties): ENABLED = no pauses all sites,
 * ENABLED_<site> = no one site (e.g. ENABLED_similar-search).
 *
 * Safeguards, per site: length limits; a hidden field and a minimum time against bots; at most LIMIT_PER_HOUR and
 * LIMIT_PER_DAY messages (Apps Script does not see the sender's address); messages expire after KEEP_HOURS, long
 * enough for GitHub's timer, which can lag by hours; the Actions put visitor text into code blocks (no links, images
 * or @mentions). Keep each site's kinds identical with its feedback.js and issue form.
 */
const SITES = {
  'box-viewer': {
    kinds: ['A box is wrong or missing', 'A text or data value is wrong', "Something doesn't work", 'An idea or wish', 'Other'],
    other: 'Other',
    text: {
      paused: 'Feedback through this form is paused; please open the issue on GitHub.',
      busy: 'There is a lot of feedback right now; please try again later or open the issue on GitHub.',
      short: 'Please describe the problem or idea.',
      fail: 'The feedback could not be sent.'
    }
  },
  'similar-search': {
    kinds: ['Ein Bezeichnungsvorschlag passt nicht', 'Ich weiss eine bessere Bezeichnung', 'Ein ähnliches Objekt passt nicht',
            'Eine Angabe oder ein Link stimmt nicht', 'Etwas funktioniert nicht', 'Idee oder Wunsch', 'Anderes'],
    other: 'Anderes',
    text: {
      paused: 'Das Formular ist pausiert; bitte die Rückmeldung auf GitHub eröffnen.',
      busy: 'Gerade kommen sehr viele Rückmeldungen an; bitte später nochmals versuchen oder die Rückmeldung auf GitHub eröffnen.',
      short: 'Bitte kurz beschreiben, was aufgefallen ist.',
      fail: 'Die Rückmeldung konnte nicht gesendet werden.'
    }
  }
};
const LEGACY_SITE = 'box-viewer';  // posts and pickups without `site`
const LIMIT_PER_HOUR = 20;         // per site
const LIMIT_PER_DAY = 100;         // per site
const KEEP_HOURS = 48;
const MAX_BYTES = 8000;            // one script property holds at most 9 kB

function doPost(e) {
  let site = LEGACY_SITE;
  try {
    const d = JSON.parse((e && e.postData && e.postData.contents) || '{}');
    site = d.site == null || d.site === '' ? LEGACY_SITE : String(d.site);
    const s = SITES[site];
    if (!s) return reply({ ok: false, error: 'Unknown site.' });
    const props = PropertiesService.getScriptProperties();
    if (paused(props, site)) return reply({ ok: false, error: s.text.paused });
    if (d.website || !(Number(d.elapsed) >= 2000)) return reply({ ok: true });  // a bot: say yes, keep nothing
    const item = {
      id: Utilities.getUuid().replace(/-/g, '').slice(0, 16), t: Date.now(), site: site,
      kind: s.kinds.indexOf(d.kind) >= 0 ? d.kind : s.other,
      // page names and inventory numbers: letters (also ä, ö, ü, é …), digits and a few signs; no @, # or links
      where: clean(d.where, 80).replace(/[^\w\sÀ-ɏ·.,:()'\/-]/g, ''),
      inv: clean(d.inv, 40).replace(/[^\w\sÀ-ɏ.\/-]/g, ''),
      details: clean(d.details, 4000), context: clean(d.context, 2000)
    };
    if (item.details.length < 5) return reply({ ok: false, error: s.text.short });
    while (bytes(item) > MAX_BYTES && item.details.length > 200) item.details = item.details.slice(0, Math.floor(item.details.length * 0.8)) + '…';
    if (bytes(item) > MAX_BYTES) item.context = item.context.slice(0, 400) + '…';
    const lock = LockService.getScriptLock();
    lock.waitLock(5000);
    try {
      if (!allow(props, site)) return reply({ ok: false, error: s.text.busy });
      props.setProperty('S:' + item.id, JSON.stringify(item));
    } finally {
      lock.releaseLock();
    }
    return reply({ ok: true, id: item.id });
  } catch (err) {
    return reply({ ok: false, error: (SITES[site] || SITES[LEGACY_SITE]).text.fail });
  }
}

function doGet(e) {
  const props = PropertiesService.getScriptProperties();
  const p = (e && e.parameter) || {};
  if (p.done) {
    props.deleteProperty('S:' + String(p.done).replace(/[^0-9a-f]/gi, ''));
    return reply({ ok: true });
  }
  const items = waiting(props);
  if (p.pending) {
    const site = p.site ? String(p.site) : LEGACY_SITE;
    return reply({ ok: true, items: items.filter(function (it) { return (it.site || LEGACY_SITE) === site; }) });
  }
  const now = Date.now(), sites = {};
  Object.keys(SITES).forEach(function (k) {
    const mine = items.filter(function (it) { return (it.site || LEGACY_SITE) === k; });
    sites[k] = { waiting: mine.length, oldest_minutes: mine.length ? Math.round((now - mine[0].t) / 60000) : 0,
                 enabled: !paused(props, k) };
  });
  return reply({ ok: true, service: 'GLAMhack 2026 feedback relay', enabled: !paused(props), sites: sites });
}

function waiting(props) {  // messages without an issue yet, oldest first; expired ones are removed
  const all = props.getProperties(), now = Date.now(), out = [];
  Object.keys(all).forEach(function (k) {
    if (k.indexOf('S:') !== 0) return;
    let it = null;
    try { it = JSON.parse(all[k]); } catch (x) { it = null; }
    if (!it || now - it.t > KEEP_HOURS * 3600000) props.deleteProperty(k); else out.push(it);
  });
  return out.sort(function (a, b) { return a.t - b.t; });
}

function paused(props, site) {  // ENABLED = no pauses all sites, ENABLED_<site> = no one site
  const off = function (k) { return String(props.getProperty(k) || 'yes').toLowerCase() === 'no'; };
  return off('ENABLED') || (site ? off('ENABLED_' + site) : false);
}

function reply(o) {
  return ContentService.createTextOutput(JSON.stringify(o)).setMimeType(ContentService.MimeType.JSON);
}

function clean(s, n) {  // plain text without control characters, at most n characters
  s = String(s == null ? '' : s).replace(/[\u0000-\u0008\u000B\u000C\u000E-\u001F\u007F]/g, '').trim();
  return s.length > n ? s.slice(0, n - 1) + '…' : s;
}

function bytes(o) {
  return Utilities.newBlob(JSON.stringify(o)).getBytes().length;
}

function allow(props, site) {  // limits per site and hour and per site and day (call inside the script lock)
  const now = Date.now(), key = 'LOG:' + site;
  const log = JSON.parse(props.getProperty(key) || '[]').filter(function (t) { return now - t < 86400000; });
  const lastHour = log.filter(function (t) { return now - t < 3600000; }).length;
  if (lastHour >= LIMIT_PER_HOUR || log.length >= LIMIT_PER_DAY) return false;
  log.push(now);
  props.setProperty(key, JSON.stringify(log));
  return true;
}
