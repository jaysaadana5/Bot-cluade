FROM node:18-alpine AS build

WORKDIR /app

# Empty API URL = use relative paths (nginx proxies /api/ to backend)
ENV REACT_APP_API_URL=
ENV NODE_OPTIONS=--openssl-legacy-provider

COPY package.json ./
# Clean install: no lock file, force lodash override
RUN rm -f package-lock.json && npm install --legacy-peer-deps
# Verify lodash version is correct (4.17.21 has assignWith)
RUN node -e "const l = require('lodash'); console.log('lodash version:', l.VERSION); if (!l.assignWith) { process.exit(1); }"

COPY . .
RUN rm -f package-lock.json
RUN npm run build

# Serve with nginx
FROM nginx:alpine
COPY --from=build /app/build /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
