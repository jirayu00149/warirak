# Self-hosted Warirak monitor (Coolify / any Docker host). Same app as the Cloudflare Worker,
# with SQLite on the /data volume instead of D1. No npm dependencies are needed at runtime.
FROM node:22-alpine
WORKDIR /app
ENV NODE_ENV=production PORT=3000 WARIRAK_DATA_DIR=/data
COPY package.json ./
COPY backend ./backend
COPY worker ./worker
COPY server ./server
COPY migrations ./migrations
COPY frontend ./frontend
COPY tools/build.mjs ./tools/build.mjs
RUN node tools/build.mjs && rm -rf frontend \
 && mkdir -p /data/backups /data/import && chown -R node:node /data
USER node
VOLUME /data
EXPOSE 3000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s CMD wget -qO- http://127.0.0.1:3000/healthz || exit 1
CMD ["node", "--disable-warning=ExperimentalWarning", "--import", "./server/register.mjs", "server/node.mjs"]
