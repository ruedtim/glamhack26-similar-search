/* Feedback on the pages of the similarity search «To Be Renamed!» – GLAMhack 2026, Völkerkundemuseum der Universität
 * Zürich. Adapted from feedback.js of the Provenance Pursuit pages (ruedtim/glamhack26-box-viewer).
 *
 * Feedback becomes an issue in the public GitHub repository ruedtim/glamhack26-similar-search, in one of two ways:
 * - With a GitHub account (the way while RELAY_DEFAULT is empty): GitHub's «new issue» page with the issue form
 *   .github/ISSUE_TEMPLATE/feedback.yml, prefilled.
 * - Without a GitHub account, once RELAY_DEFAULT names a relay: a small form on the page sends the feedback there (an
 *   inbox outside GitHub, e.g. a Google Apps Script web app); a scheduled GitHub Action fetches the messages and
 *   opens the issues with GitHub's own token, so no personal token is stored anywhere.
 * Both carry where the feedback comes from: the page, its online address (also when the page is opened from the
 * offline copy – never the local file path) and the object. Issues are public, so the form asks for no names of
 * private persons and no contact details.
 *
 * Load once per page, after the button (feedback.py writes both):  <script src="feedback.js"></script>  (review/: ../)
 * - a.feedback, the button at the top right, reports on the page, or on the object the address points to (#o-…).
 * - a.ppfb-link with data-ppfb='{"inv": …, "title": …}' reports on one object; the enclosing element with an id o-…
 *   gives its anchor. Both stay plain links to GitHub's form when JavaScript is off.
 * - ppFeedback.url(ctx) gives the GitHub address, ppFeedback.html(ctx, text) such a link as HTML, ppFeedback.open(ctx)
 *   the form. ctx, all optional: inv, title, anchor ('o-…'), kind (one of ppFeedback.KINDS), note (one line).
 * - window.ppFeedbackRelay = '' before this script switches the relay off (straight to GitHub), or names another relay.
 * Keep KINDS identical with the issue form .github/ISSUE_TEMPLATE/feedback.yml (and with the relay, if one is set).
 */
(() => {
  if (window.ppFeedback) return;
  const REPO = 'https://github.com/ruedtim/glamhack26-similar-search';
  const SITE = 'https://ruedtim.github.io/glamhack26-similar-search/';
  const RELAY_DEFAULT = '';  // address of a feedback relay, e.g. a Google Apps Script web app (https://script.google.com/macros/s/…/exec)
  const RELAY = typeof window.ppFeedbackRelay === 'string' ? window.ppFeedbackRelay : RELAY_DEFAULT;
  const KINDS = ['Ein Bezeichnungsvorschlag passt nicht', 'Ich weiss eine bessere Bezeichnung',
                 'Ein ähnliches Objekt passt nicht', 'Eine Angabe oder ein Link stimmt nicht', 'Etwas funktioniert nicht',
                 'Idee oder Wunsch', 'Anderes'];
  const PAGES = { '': 'Übersicht', 'index.html': 'Übersicht', 'review/': 'VMZ-Liste', 'review/index.html': 'VMZ-Liste',
                  'review/mkb.html': 'MKB-Liste' };
  const FAIL = 'Die Rückmeldung konnte nicht gesendet werden.';
  const ANCHOR = /^o-[\w.-]+$/;
  // the site root is the folder of this script, online and in the offline copy alike
  const BASE = new URL('.', (document.currentScript && document.currentScript.src) || location.href).href;
  const cut = (s, n) => { s = String(s ?? '').replace(/\s+/g, ' ').trim(); return s.length > n ? s.slice(0, n - 1) + '…' : s; };
  const esc = s => String(s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]);

  function rel() {  // this page below the site root, e.g. 'review/mkb.html'
    const here = location.href.split('#')[0].split('?')[0];
    return here.startsWith(BASE) ? here.slice(BASE.length) : here.split('/').pop();
  }
  function hashAnchor() {
    try { const h = decodeURIComponent(location.hash.slice(1)); return ANCHOR.test(h) ? h : ''; } catch { return ''; }
  }
  function address(anchor) {  // the online address, so the local path of an offline copy is never sent
    const a = anchor || hashAnchor();
    return SITE + rel() + (a ? '#' + a : '') + (location.protocol === 'file:' ? ' (Offline-Kopie)' : '');
  }
  function browser() {
    const ua = navigator.userAgent;
    const name = /Edg\//.test(ua) ? 'Edge' : /Firefox\//.test(ua) ? 'Firefox' : /Chrome\//.test(ua) ? 'Chrome'
      : /Safari\//.test(ua) ? 'Safari' : 'anderer Browser';
    const os = /iPhone|iPad/.test(ua) ? 'iOS' : /Android/.test(ua) ? 'Android' : /Mac OS X/.test(ua) ? 'macOS'
      : /Windows/.test(ua) ? 'Windows' : /Linux/.test(ua) ? 'Linux' : 'anderes System';
    return `${name} auf ${os}, Fenster ${innerWidth} × ${innerHeight}`;
  }
  function parse(a) {
    try { const c = JSON.parse(a.dataset.ppfb || '{}'); return c && typeof c === 'object' ? c : {}; } catch { return {}; }
  }
  function fromAnchor(anchor) {  // the object an anchor points to, from the feedback link in its section
    const el = anchor && document.getElementById(anchor);
    const a = el && el.querySelector('a.ppfb-link[data-ppfb]');
    return a ? { ...parse(a), anchor } : el ? { anchor } : {};
  }
  function pageContext() {
    try { if (typeof window.ppFeedbackContext === 'function') return window.ppFeedbackContext() || {}; } catch { return {}; }
    return fromAnchor(hashAnchor());
  }
  function linkContext(a) {
    if (a.classList.contains('feedback')) return pageContext();
    const ctx = parse(a), holder = a.closest('[id^="o-"]');
    return holder && !ctx.anchor ? { ...ctx, anchor: holder.id } : ctx;
  }

  // what is sent along: «where» and the inventory number for the issue title, lines for the reader of the issue
  function about(ctx) {
    const c = ctx || {}, where = PAGES[rel()] || 'Ähnlichkeitssuche';
    const lines = [`Seite: ${where}`, `Adresse: ${cut(address(ANCHOR.test(c.anchor || '') ? c.anchor : ''), 600)}`];
    if (c.inv) lines.push(`Objekt: Inv.-Nr. ${cut(c.inv, 40)}` + (c.title ? ` · ${cut(c.title, 120)}` : ''));
    else if (c.title) lines.push(`Objekt: ${cut(c.title, 160)}`);
    if (c.note) lines.push(`Hinweis: ${cut(c.note, 300)}`);
    lines.push(`Browser: ${browser()}`);
    const inv = c.inv ? cut(c.inv, 40) : '';
    return { where, inv, kind: KINDS.includes(c.kind) ? c.kind : '', lines,
             title: cut('Feedback: ' + [where, inv && `Inv.-Nr. ${inv}`].filter(Boolean).join(' · '), 120) };
  }
  function url(ctx, typed) {  // GitHub's issue form, prefilled; `typed`: what was already written into the form here
    const a = about(ctx), t = typed || {};
    const q = new URLSearchParams({ template: 'feedback.yml', title: a.title });
    if (t.kind || a.kind) q.set('kind', t.kind || a.kind);
    if (t.details) q.set('details', String(t.details).slice(0, 3000));
    q.set('context', typeof t.context === 'string' ? t.context.slice(0, 2000) : a.lines.join('\n'));
    return `${REPO}/issues/new?${q}`;
  }
  const html = (ctx, text = 'Rückmeldung zu diesem Objekt') =>
    `<a class="ppfb-link" href="${esc(url(ctx))}" data-ppfb="${esc(JSON.stringify(ctx || {}))}" target="_blank" rel="noopener">${esc(text)}</a>`;
  window.ppFeedback = { url: ctx => url(ctx), html, KINDS, open: ctx => form(ctx || pageContext()) };

  const css = `
.ppfb-dialog { width: min(560px, calc(100vw - 32px)); max-height: calc(100vh - 32px); box-sizing: border-box; padding: 18px 18px 14px;
  border: 1px solid rgba(0,0,0,.16); border-radius: 12px; background: #fff; color: #1c1b19;
  font: 15px/1.45 system-ui, -apple-system, "Segoe UI", sans-serif; box-shadow: 0 10px 40px rgba(0,0,0,.25); }
.ppfb-dialog::backdrop { background: rgba(0,0,0,.35); }
.ppfb-dialog h2 { margin: 0 0 6px; font-size: 18px; }
.ppfb-dialog p { margin: 0 0 12px; }
.ppfb-dialog .ppfb-note { font-size: 13px; color: #5d5951; }
.ppfb-dialog label { display: block; margin: 0 0 12px; font-weight: 600; font-size: 14px; }
.ppfb-dialog select, .ppfb-dialog textarea { display: block; width: 100%; box-sizing: border-box; margin-top: 4px;
  font-family: inherit; font-size: 14px; line-height: 1.4; font-weight: 400; color: inherit; background: transparent;
  border: 1px solid rgba(0,0,0,.25); border-radius: 8px; padding: 7px 9px; }
.ppfb-dialog textarea[name=context] { font: 12px/1.4 ui-monospace, "SF Mono", Menlo, Consolas, monospace; color: #5d5951; }
.ppfb-dialog .ppfb-hp { position: absolute; left: -9999px; width: 1px; height: 1px; opacity: 0; }
.ppfb-dialog .ppfb-status { min-height: 1.4em; font-size: 14px; }
.ppfb-dialog .ppfb-status.bad { color: #b3261e; }
.ppfb-dialog .ppfb-status.good { color: #1a7f4b; }
.ppfb-dialog .ppfb-status a { color: inherit; }
.ppfb-dialog .ppfb-actions { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; justify-content: flex-end; }
.ppfb-dialog .ppfb-actions a { margin-right: auto; font-size: 13px; color: inherit; }
.ppfb-dialog button { font-family: inherit; font-size: 14px; font-weight: 600; line-height: 1; padding: 9px 14px;
  border-radius: 8px; cursor: pointer; border: 1px solid rgba(0,0,0,.25); background: transparent; color: inherit; }
.ppfb-dialog button.ppfb-send { background: #8a3b12; border-color: #8a3b12; color: #fff; }
.ppfb-dialog button:disabled { opacity: .55; cursor: default; }
.ppfb-dialog :focus-visible { outline: 2px solid #2166ac; outline-offset: 2px; }
@media (prefers-color-scheme: dark) {
  .ppfb-dialog { background: #22201d; color: #ece9e3; border-color: rgba(255,255,255,.18); }
  .ppfb-dialog .ppfb-note, .ppfb-dialog textarea[name=context] { color: #a29d94; }
  .ppfb-dialog select, .ppfb-dialog textarea, .ppfb-dialog button { border-color: rgba(255,255,255,.25); }
  .ppfb-dialog select option { background: #22201d; }
  .ppfb-dialog .ppfb-status.bad { color: #ff8a7a; }
  .ppfb-dialog .ppfb-status.good { color: #52c891; }
  .ppfb-dialog button.ppfb-send { background: #e0a24a; border-color: #e0a24a; color: #191917; }
  .ppfb-dialog :focus-visible { outline-color: #8fb8e8; } }`;

  // ---------------------------------------------------------------- the form (only with a relay)
  let dlg = null, opened = 0, current = null;
  function build() {
    const s = document.createElement('style');
    s.textContent = css;
    document.head.appendChild(s);
    dlg = document.createElement('dialog');
    dlg.className = 'ppfb-dialog';
    dlg.setAttribute('aria-labelledby', 'ppfb-h');
    dlg.innerHTML = `<form method="dialog">
  <h2 id="ppfb-h">Feedback</h2>
  <p class="ppfb-note">Die Rückmeldung wird in etwa 10 bis 20 Minuten zu einem <b>öffentlichen</b> Issue auf GitHub;
    ein GitHub-Konto ist nicht nötig. Bitte keine Namen von Privatpersonen und keine eigenen Kontaktdaten angeben.</p>
  <label>Worum geht es?<select name="kind" required><option value="">Bitte wählen …</option>${KINDS.map(k => `<option>${esc(k)}</option>`).join('')}</select></label>
  <label>Was ist aufgefallen, und was wäre richtig?<textarea name="details" rows="5" required minlength="5" maxlength="4000"
    placeholder="Zum Beispiel: Der Vorschlag «Maske» passt nicht, auf dem Foto ist ein Kopfschmuck."></textarea></label>
  <label>Wird mitgeschickt (von der Seite ausgefüllt, änderbar)<textarea name="context" rows="4" maxlength="2000"></textarea></label>
  <input class="ppfb-hp" name="website" tabindex="-1" autocomplete="off" aria-hidden="true">
  <p class="ppfb-status" role="status" aria-live="polite"></p>
  <div class="ppfb-actions">
    <a class="ppfb-gh" href="${esc(REPO)}/issues/new?template=feedback.yml" target="_blank" rel="noopener">Stattdessen auf GitHub eröffnen</a>
    <button type="submit" value="cancel" formnovalidate>Schliessen</button>
    <button type="submit" value="send" class="ppfb-send">Senden</button>
  </div>
</form>`;
    document.body.appendChild(dlg);
    const f = dlg.querySelector('form'), gh = dlg.querySelector('.ppfb-gh');
    f.addEventListener('submit', send);
    f.details.addEventListener('input', () => { f.querySelector('.ppfb-send').disabled = false; });  // ready for the next
    const carry = () => { gh.href = url(current.ctx, { kind: f.kind.value, details: f.details.value, context: f.context.value }); };
    gh.addEventListener('click', carry);
    gh.addEventListener('auxclick', carry);
  }
  function form(ctx) {
    if (!RELAY) { window.open(url(ctx), '_blank', 'noopener'); return; }
    if (!dlg) build();
    current = { ctx, ...about(ctx) };
    const f = dlg.querySelector('form');
    f.kind.value = current.kind;
    f.context.value = current.lines.join('\n');
    status('', '');
    f.querySelector('.ppfb-send').disabled = false;
    opened = Date.now();
    if (!dlg.open) dlg.showModal();
    (current.kind ? f.details : f.kind).focus();
  }
  function status(text, cls, href, linkText) {
    const s = dlg.querySelector('.ppfb-status');
    s.className = 'ppfb-status' + (cls ? ' ' + cls : '');
    s.textContent = text;
    if (href) {
      const a = document.createElement('a');
      a.href = href;
      a.target = '_blank';
      a.rel = 'noopener';
      a.textContent = linkText;
      s.append(' ', a);
    }
  }
  async function send(ev) {
    if (ev.submitter && ev.submitter.value !== 'send') return;  // «Schliessen»: the dialog closes by itself
    ev.preventDefault();
    const f = ev.target, button = f.querySelector('.ppfb-send');
    if (!f.reportValidity()) return;
    button.disabled = true;
    status('Wird gesendet …', '');
    try {
      const r = await fetch(RELAY, { method: 'POST', body: JSON.stringify({  // text/plain: no preflight request
        kind: f.kind.value, details: f.details.value, context: f.context.value, where: current.where, inv: current.inv,
        website: f.website.value, elapsed: Date.now() - opened }) });
      const j = await r.json();
      if (!j.ok) throw Object.assign(new Error(j.error || FAIL), { relay: true });
      f.details.value = '';
      status('Danke! In etwa 10 bis 20 Minuten erscheint die Rückmeldung als öffentliches Issue auf GitHub.', 'good',
             `${REPO}/issues?q=${encodeURIComponent('label:"via form"')}`, 'Alle Rückmeldungen ansehen');
    } catch (e) {
      button.disabled = false;
      const msg = e && e.relay ? e.message
        : navigator.onLine === false ? 'Ohne Internetverbindung lässt sich die Rückmeldung nicht senden.' : FAIL;
      status(/GitHub/.test(msg) ? msg : `${msg} Sie lässt sich auch über «Stattdessen auf GitHub eröffnen» senden.`, 'bad');
    }
  }

  // ---------------------------------------------------------------- the button and the links
  const plain = e => e.button === 0 && !e.metaKey && !e.ctrlKey && !e.shiftKey && !e.altKey;
  function onClick(e) {
    const a = e.target.closest && e.target.closest('a.feedback, a.ppfb-link');
    if (!a) return;
    const ctx = linkContext(a);  // the context at the moment of the click
    a.href = url(ctx);           // GitHub, prefilled, if the link opens after all (no relay, new tab, middle click)
    if (e.type === 'click' && RELAY && plain(e)) { e.preventDefault(); form(ctx); }
  }
  document.addEventListener('click', onClick);
  document.addEventListener('auxclick', onClick);
})();
