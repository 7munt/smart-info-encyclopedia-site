# Smart Info Encyclopedia

**المعلومة الذكية – Smart Info Encyclopedia** is a bilingual Arabic/English knowledge website built with plain HTML, CSS, and JavaScript.

## Project structure

- `index.html` — homepage, category browsing, article search, and site navigation.
- `articles/` — ten bilingual educational articles with section navigation and further-reading references.
- `assets/brand.css` — shared visual system for internal pages and articles.
- `favicon.svg` — the site emblem: an open book with a digital spark.
- `about.html`, `contact.html` — about and contact information.
- `privacy.html`, `terms.html` — bilingual privacy policy and terms of use.
- `editorial-policy.html` — editorial standards.
- `robots.txt`, `sitemap.xml` — crawler guidance and the list of public pages.

## Local preview

This is a static website; there is no build command or package installation.

1. Download or clone the repository.
2. Open `index.html` in a browser, or serve the folder with any static HTTP server.
3. Check Arabic and English language switching, search, article links, and mobile layout.

## Cloudflare Pages

The intended deployment configuration is:

- Production branch: `main`
- Build command: leave empty
- Build output directory: `/` (repository root)

A push to `main` should trigger a deployment when the Cloudflare Pages project is connected to this repository. Confirm the deployment status in the Cloudflare dashboard; a GitHub commit alone does not prove that the live site has updated.

## Before applying for Google AdSense

- Review every article for accuracy, depth, original value, and working references.
- Test all navigation and language controls on desktop and mobile.
- Confirm the live website and all public pages load without errors.
- Keep the privacy policy accurate for the services actually enabled.
- Add the AdSense verification code only after receiving it from the AdSense account.
- Do not add a placeholder publisher ID or claim that AdSense is active before approval.

The presence of legal pages and a sitemap does not guarantee AdSense approval. Google reviews the whole site and its content against current program policies.
