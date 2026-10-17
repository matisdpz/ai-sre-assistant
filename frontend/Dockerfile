# Stage 1: build the static files with Node.
FROM node:22-alpine AS build
WORKDIR /app
# npm 10 (bundled with Node 22) crashes resolving vitest's peer dependencies.
RUN npm install -g npm@11.21.0
COPY package.json package-lock.json .npmrc ./
RUN npm ci --no-audit --no-fund
COPY tsconfig.json vite.config.ts index.html ./
COPY src ./src
RUN npm run build

# Stage 2: only nginx and the built files; Node and node_modules are left behind.
FROM nginx:1.28-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
