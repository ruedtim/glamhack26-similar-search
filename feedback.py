"""Feedback button for the published pages: a prominent link at the top right that opens a prefilled GitHub issue
form (.github/ISSUE_TEMPLATE/feedback.yml). A static page cannot create an issue by itself without exposing a token,
so GitHub shows the form and the person submits it (a GitHub account is needed). The click adds the online address of
the page (also when it is opened from the offline ZIP, without the local file path) and, after a jump to an object,
its anchor.
"""
import html
from urllib.parse import urlencode

REPO = "https://github.com/ruedtim/glamhack26-similar-search"
SITE = "https://ruedtim.github.io/glamhack26-similar-search/"

FEEDBACK_CSS = """
.feedback{position:fixed;top:10px;right:16px;z-index:20;display:inline-flex;align-items:center;gap:6px;
padding:8px 15px;border-radius:999px;background:#8a3b12;color:#fff;font:600 14px/1.2 system-ui,sans-serif;
text-decoration:none;box-shadow:0 2px 10px rgba(0,0,0,.2)}
.feedback:hover,.feedback:focus-visible{background:#6d2d0c}
.feedback svg{width:16px;height:16px;flex:none}
@media (prefers-color-scheme: dark){.feedback{background:#e0a24a;color:#191917}.feedback:hover,.feedback:focus-visible{background:#f0b862}}
.bar{padding-right:132px}
@media (max-width:760px){body{padding-top:56px}}
@media print{.feedback{display:none}}
"""

ICON = ('<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" '
        'stroke-linejoin="round" aria-hidden="true"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 '
        '2 2z"/></svg>')

SCRIPT = """<script>
document.querySelector('a.feedback').addEventListener('click', e => {
  const a = e.currentTarget, u = new URL(a.href);
  u.searchParams.set('seite', a.dataset.site + a.dataset.page + location.hash);
  if (location.hash.startsWith('#o-')) u.searchParams.set('objekt', decodeURIComponent(location.hash.slice(3)));
  a.href = u.toString();
});
</script>"""


def feedback_html(page, label):
    """Button for one page: `page` is its path below SITE (e.g. 'review/mkb.html'), `label` names it in the title."""
    url = f"{REPO}/issues/new?" + urlencode({"template": "feedback.yml", "title": f"Feedback: {label}",
                                             "seite": SITE + page})
    return (f'<a class="feedback" href="{html.escape(url)}" target="_blank" rel="noopener" '
            f'data-site="{SITE}" data-page="{html.escape(page)}" '
            f'title="Rückmeldung als GitHub-Issue (öffnet GitHub; ein GitHub-Konto ist nötig)">{ICON}Feedback</a>'
            + SCRIPT)
