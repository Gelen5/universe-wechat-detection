FROM node:24.18.0-bookworm-slim
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --omit=dev --ignore-scripts
COPY src ./src
USER node
CMD ["node", "src/server.mjs"]
