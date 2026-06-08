FROM node:20-alpine

WORKDIR /app

COPY apps/web/package.json /app/package.json
COPY apps/web/package-lock.json /app/package-lock.json

RUN npm ci

COPY apps/web /app

RUN npm run build && npm prune --omit=dev

EXPOSE 3000

CMD ["npm", "run", "serve"]
