FROM node:24-alpine AS build

WORKDIR /app
COPY agent-framework/double-charge/maf/frontend/package*.json agent-framework/double-charge/maf/frontend/.npmrc ./
RUN npm ci
COPY agent-framework/double-charge/maf/frontend/ ./
RUN npm run build

FROM nginx:1.29-alpine
COPY agent-framework/double-charge/maf/infra/app/nginx.conf.template /etc/nginx/templates/default.conf.template
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
