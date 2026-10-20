# The production UI for `docker compose up` (service `web`): the Vite build, served by nginx, which
# also forwards /api/ and /health to the `api` service, so the browser talks to one origin (the
# backend sends no CORS headers). The build calls the real API: MSW runs only in dev and in tests.

FROM node:24-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
RUN npm run build

# nginx's unprivileged variant: it runs as the nginx user (uid 101) and listens on 8080.
FROM nginxinc/nginx-unprivileged:1.28-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 8080
