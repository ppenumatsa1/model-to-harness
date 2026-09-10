FROM node:24-alpine AS build

WORKDIR /app
COPY agent-framework/double-charge/langgraph/frontend/package*.json ./
RUN npm ci
COPY agent-framework/double-charge/langgraph/frontend/ ./
RUN npm run build

FROM nginx:1.29-alpine
ARG SOURCE_COMMIT
ARG SOURCE_SHA256
LABEL org.opencontainers.image.revision=$SOURCE_COMMIT
LABEL io.model-to-harness.source-sha256=$SOURCE_SHA256
COPY agent-framework/double-charge/langgraph/infra/app/nginx.conf.template /etc/nginx/templates/default.conf.template
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
