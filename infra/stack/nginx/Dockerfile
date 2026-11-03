# 포털 웹(정적 파일) 빌드 후 nginx 이미지에 포함. 빌드 컨텍스트는 저장소 루트.
FROM node:22.11.0-alpine AS web
WORKDIR /web
COPY apps/web/package.json apps/web/package-lock.json ./
RUN npm ci
COPY apps/web ./
RUN npm run build

FROM nginx:1.27.2-alpine
COPY infra/stack/nginx/default.conf /etc/nginx/conf.d/default.conf
COPY --from=web /web/out /usr/share/nginx/html
