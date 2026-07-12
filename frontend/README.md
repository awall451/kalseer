# Kalseer frontend

Svelte 5 + Vite + ECharts single-page dashboard. `npm install` then
`npm run build` writes the static bundle into `../site/` (served by nginx;
the runtime JSON under `./data/` comes from `publish.py`, not the build).

`npm run dev` serves a live-reload dev build; point it at real data by
symlinking or copying a `data/` dir into the dev server root, or just use
`docker compose up` at the repo root for the production-shaped setup.

See the root README for the wiki authoring guide.
