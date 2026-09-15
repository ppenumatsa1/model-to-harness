FROM node:22-alpine AS build
WORKDIR /app
COPY harness/checkout-recovery/maf/frontend/package.json harness/checkout-recovery/maf/frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY harness/checkout-recovery/maf/frontend/index.html ./
COPY harness/checkout-recovery/maf/frontend/tsconfig*.json harness/checkout-recovery/maf/frontend/vite.config.ts harness/checkout-recovery/maf/frontend/vitest.config.ts harness/checkout-recovery/maf/frontend/playwright.config.ts ./
COPY harness/checkout-recovery/maf/frontend/src ./src
COPY harness/checkout-recovery/maf/frontend/e2e ./e2e
RUN npm run build

FROM nginx:1.28-alpine
COPY --from=build /app/dist /usr/share/nginx/html
COPY harness/checkout-recovery/maf/frontend/nginx/default.conf.template /opt/checkout/default.conf.template
COPY --chmod=755 harness/checkout-recovery/maf/frontend/nginx/entrypoint.sh /usr/local/bin/checkout-entrypoint
EXPOSE 8080
ENTRYPOINT ["/usr/local/bin/checkout-entrypoint"]
CMD ["nginx", "-g", "daemon off;"]
