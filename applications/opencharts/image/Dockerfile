# OpenCharts — static SPA (Vite/React, no backend).
# Stage 1 builds dist/, stage 2 serves it from unprivileged nginx on :8080.
FROM node:22.23.5-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY . .
# base defaults to "/" (vite.config.ts) — correct for a domain-root deploy.
RUN npm run build

FROM nginxinc/nginx-unprivileged:1.31-alpine
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 8080
