FROM node:20-alpine

WORKDIR /app
COPY frontend/package.json /app/package.json
COPY frontend/package-lock.json /app/package-lock.json
COPY frontend/tsconfig.json /app/tsconfig.json
COPY frontend/next.config.js /app/next.config.js
COPY frontend/next-env.d.ts /app/next-env.d.ts
COPY frontend/app /app/app
COPY frontend/components /app/components
COPY frontend/hooks /app/hooks
COPY frontend/lib /app/lib

RUN npm ci

EXPOSE 3000
CMD ["npm", "run", "dev", "--", "--hostname", "0.0.0.0", "--port", "3000"]
