FROM sms-mvp-frontend:latest

WORKDIR /app

COPY apps/web /app

EXPOSE 3000

CMD ["node", "server.js"]
