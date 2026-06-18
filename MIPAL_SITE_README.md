# MIPA Laboratory GitHub Pages Site

This branch contains a lightweight Markdown-driven homepage for MIPA Laboratory.

## Edit Content

- `content/home.md` - main page text
- `content/notice.md` - announcements
- `content/members.md` - people
- `content/publications.md` - papers and research output
- `content/gallery.md` - gallery captions and image links

The layout lives in `index.html`, `styles.css`, and `app.js`.

## Publish

This repository is `nojunk/nojunk.github.io`, so merging this branch into the Pages branch will make the site available at `https://nojunk.github.io/` after GitHub Pages finishes deploying.

To serve the site at `mipal.snu.ac.kr`, add a `CNAME` file containing `mipal.snu.ac.kr`, then configure the DNS record for the domain in GitHub Pages settings.

## Local Preview

Because the site loads Markdown files with `fetch`, preview it through a local web server instead of opening `index.html` directly.

```bash
python -m http.server 8080
```

Then open `http://localhost:8080`.
