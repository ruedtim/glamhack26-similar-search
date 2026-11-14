# Feedback relay (shared by two sites)

One Google Apps Script web app (`Code.gs`) takes feedback without a GitHub account for two GLAMhack 2026 sites:

- `similar-search` – this repository: form in `docs/feedback.js`, Action `.github/workflows/feedback.yml`;
- `box-viewer` – Provenance Pursuit (`ruedtim/glamhack26-box-viewer`). Its form and Action from before the shared
  relay send no site; such messages and pickups count as `box-viewer`.

The relay keeps each message for up to 48 hours. Each repository's Action fetches its own new messages every
10 minutes (`?pending=1&site=…`), opens one issue each with GitHub's own token (labels `feedback`, `via form`, author
`github-actions[bot]`) and then removes the message. No personal token is stored anywhere.

## Set up (once)

1. On script.google.com: New project, paste `Code.gs`, save.
2. Deploy → New deployment → Web app; Execute as: Me; Who has access: Anyone (not «Anyone with a Google
   account»). Copy the web app address (`…/exec`). It is not a secret: it ends up in the published pages anyway.
3. This repository: put the address into `RELAY_DEFAULT` in `docs/feedback.js` and `RELAY_URL` in
   `.github/workflows/feedback.yml`, create the label `via form`, publish, rebuild the offline ZIP.
4. Box viewer: the same address into its `feedback.js` (`RELAY_DEFAULT`) and its workflow (`RELAY_URL`); nothing
   else changes there. Alternatively, replace the code of its existing Apps Script project with this `Code.gs` and
   deploy a new version of the existing deployment (Deploy → Manage deployments → edit → Version: New version):
   then its address stays the same and only this repository needs it.
5. Another site: an entry in `SITES` (kinds and texts), a new version of the deployment, then `site` in that
   site's form and `&site=` in its Action.

## Run it

- Status: opening the web app address shows per site how many messages wait and how old the oldest one is. If
  that age grows beyond 10–20 minutes, the site's Action has not run. GitHub's timer can lag, especially in the
  first hours of a new workflow; start it by hand under Actions → Run workflow.
- Pause without redeploying (Project settings → Script properties): `ENABLED` = `no` for all sites,
  `ENABLED_similar-search` = `no` for one site; the form then points to GitHub. Stop: archive the deployment, or
  disable a site's workflow.
- Limits per site: 20 messages per hour and 100 per day; a hidden field and a minimum time keep simple bots out.
  Visitor text goes into the issue as plain text (code blocks), so it cannot add links, images or @mentions.
- The form sends the online address of the page, also from the offline copy, never the local file path.
- `?pending=1&site=…` lists the waiting messages (they become public issues anyway). Anyone could also remove a
  waiting message with `?done=<id>`; for a hackathon that is accepted.
- Close unwanted issues rather than deleting them: a deleted one could come back while its message is still kept.
- GitHub switches off scheduled workflows in public repositories after 60 days without any commit. Then
  re-enable the workflow under Actions (or push a commit).
- Kinds: keep `SITES[…].kinds` in `Code.gs` identical with the site's `feedback.js` and issue form; after a change
  in `Code.gs`, deploy a new version.
