"""Feedback on the published pages: the button «Feedback» at the top right of every page and, in the two lists, a link
«Rückmeldung zu diesem Objekt» at each object. Both are plain links to GitHub's prefilled issue form
(.github/ISSUE_TEMPLATE/feedback.yml), so they work without JavaScript too. docs/feedback.js, loaded by every page,
adds where the feedback comes from: the page, its online address (also from the offline copy, without the local file
path) and the object; once a relay is set there, it shows a small form on the page instead (no GitHub account needed).
Issues are public: the links carry only the inventory number and the name that the page shows anyway.
"""
import html
import json

REPO = "https://github.com/ruedtim/glamhack26-similar-search"
FORM =REPO + "/issues/new?template=feedback.yml"
TIP = "Rückmeldung senden – sie wird ein öffentliches GitHub-Issue"

FEEDBACK_CSS = """
.feedback{position:fixed;top:10px;right:16px;z-index:20;display:inline-flex;align-items:center;gap:6px;
padding:8px 15px;border-radius:999px;background:#8a3b12;color:#fff;font:600 14px/1.2 system-ui,sans-serif;
text-decoration:none;box-shadow:0 2px 10px rgba(0,0,0,.2)}
.feedback:hover,.feedback:focus-visible{background:#6d2d0c}
.feedback svg{width:16px;height:16px;flex:none}
a.ppfb-link{color:inherit;text-underline-offset:2px}
@media (prefers-color-scheme: dark){.feedback{background:#e0a24a;color:#191917}.feedback:hover,.feedback:focus-visible{background:#f0b862}}
.bar{padding-right:132px}
@media (max-width:760px){body{padding-top:56px}}
@media print{.feedback,a.ppfb-link{display:none}}
"""

ICON = ('<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" '
        'stroke-linejoin="round" aria-hidden="true"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 '
        '2 2z"/></svg>')


def feedback_html(root=""):
    """The button at the top right and the script; `root` leads from the page to the site root ('' or '../')."""
    return (f'<a class="feedback" href="{html.escape(FORM)}" target="_blank" rel="noopener" title="{TIP}">{ICON}Feedback</a>'
            f'<script src="{root}feedback.js"></script>')


def object_link(inv, name):
    """«Rückmeldung zu diesem Objekt» for one object; the section around it (id o-…) gives the anchor."""
    ctx = html.escape(json.dumps({"inv": inv, "title": name or ""}, ensure_ascii=False))
    return (f'<a class="ppfb-link" href="{html.escape(FORM)}" data-ppfb="{ctx}" target="_blank" rel="noopener" '
            f'title="{TIP}">Rückmeldung zu diesem Objekt</a>')
