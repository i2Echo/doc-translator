FROM sms-mvp-frontend:latest

RUN apk add --no-cache redis

EXPOSE 6379
