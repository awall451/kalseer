# Dashboard image: static SPA on unprivileged nginx. No trading data is
# baked in — the runtime ./data/ JSON is volume-mounted (see charts/kalseer).
FROM node:22-alpine AS build
WORKDIR /app
COPY frontend/package.json frontend/package-lock.json frontend/
RUN cd frontend && npm ci
COPY frontend/ frontend/
RUN cd frontend && npm run build

FROM nginxinc/nginx-unprivileged:1.29-alpine
COPY --from=build /app/site /usr/share/nginx/html
EXPOSE 8080
