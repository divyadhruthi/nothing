# SVR Kishore — portfolio

A static, single-page portfolio with no build step or runtime dependencies.

## Deploy with GitHub Pages

1. Put the **contents of this folder** at the root of a GitHub repository. Keep `.github/workflows/`, `assets/`, `data/`, and `scripts/` at the repository root alongside `index.html`.
2. Push the `main` branch.
3. In the repository, open **Settings → Pages** and set the source to **GitHub Actions**.
4. The `Deploy portfolio to GitHub Pages` workflow publishes the site on pushes to `main`. The sync workflow also calls it, but only when a sync actually committed new data. The deployment URL appears in the workflow run and in the Pages settings.

## Deploy with Vercel

Import the repository in Vercel and use the portfolio folder as the project root if it is inside a larger repository. Leave the framework preset as **Other**, with no build command and `.` as the output directory. The site is static; its relative asset and JSON paths work on a project subpath as well.

## Projects

The Projects section is driven by `data/projects.json`. Each entry is shown in the order listed:

- `name`, `description`, `tags`, `outcome`: what the card shows.
- `repo`: the GitHub repository name. Stars, dates and the GitHub link come from the synced repo data. An entry whose repo is not public is hidden unless it has `"alwaysShow": true`, in which case it links to the GitHub profile.
- `homepage`: optional live-demo link (overrides the repo's homepage).

Other public repositories appear after the curated ones only if they have the GitHub topic named by `extraTopic` (default `portfolio`). Add that topic to a repo on GitHub to show it; nothing else is listed automatically.

## Profile data sync

The workflow in `.github/workflows/sync.yml` refreshes GitHub projects, LeetCode, and GeeksforGeeks profile stats on a schedule and supports manual runs from the Actions tab. Each source is saved independently: if one fails (the GeeksforGeeks page scrape is the most fragile), the others are still committed and deployed, and the run is marked failed with a warning naming the source. The page checks the JSON files every minute. Runs may be delayed, and the platforms do not send live solve events directly to this static site.

The sync also rebuilds the static HTML between the `<!-- generated:… -->` markers in `index.html`, so search engines, link previews and visitors without JavaScript see current projects and stats. After editing `data/projects.json` locally, refresh that HTML without any network calls:

```bash
python scripts/sync.py --render-only
```

Update usernames and profile addresses in `scripts/config.json`. GeeksforGeeks exposes limited public stats, so its sync may only provide problems solved, coding score, and institute rank when available. Keep GitHub Actions enabled and allow the workflow to write repository contents so refreshed snapshots can be committed.

## Contact and resume

The contact form has two modes, chosen by the `data-endpoint` attribute on `<form id="contactForm">` in `index.html`:

- Empty (default): it opens a prefilled email with `mailto:`. Visitors without a mail app see the address to write to directly.
- A form-service URL (for example `https://formspree.io/f/<your-form-id>`): it sends the message directly and shows sending, sent and failed states. The service must accept a JSON `POST`. The hidden `_gotcha` field is a spam honeypot that Formspree recognises.

The footer currently offers a resume request by email because a resume PDF has not been added. To offer a download, place the approved PDF at `assets/Kishore-Resume.pdf` and change the footer link in `index.html` to that file.

## Local preview

Run a static server from this folder (for example, `python -m http.server`) and open the local address it prints. Serving the files over HTTP lets the browser read the JSON snapshots.
