FROM node:22-alpine AS build
WORKDIR /app
COPY harness/checkout-recovery/copilot-sdk/frontend/package.json harness/checkout-recovery/copilot-sdk/frontend/package-lock.json harness/checkout-recovery/copilot-sdk/frontend/.npmrc ./
RUN npm ci --no-audit --no-fund
COPY harness/checkout-recovery/copilot-sdk/frontend/index.html ./
COPY harness/checkout-recovery/copilot-sdk/frontend/tsconfig*.json harness/checkout-recovery/copilot-sdk/frontend/vite.config.ts harness/checkout-recovery/copilot-sdk/frontend/vitest.config.ts harness/checkout-recovery/copilot-sdk/frontend/playwright.config.ts ./
COPY harness/checkout-recovery/copilot-sdk/frontend/src ./src
COPY harness/checkout-recovery/copilot-sdk/frontend/e2e ./e2e
RUN npm run build

FROM nginx:1.28-alpine
COPY --from=build /app/dist /usr/share/nginx/html
COPY harness/checkout-recovery/copilot-sdk/frontend/nginx/default.conf.template /opt/checkout/default.conf.template
COPY --chmod=755 harness/checkout-recovery/copilot-sdk/frontend/nginx/entrypoint.sh /usr/local/bin/checkout-entrypoint
EXPOSE 8080
ENTRYPOINT ["/usr/local/bin/checkout-entrypoint"]
CMD ["nginx", "-g", "daemon off;"]
