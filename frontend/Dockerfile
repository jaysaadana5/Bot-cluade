FROM node:20-alpine AS build

WORKDIR /app

# Empty API URL = use relative paths (nginx proxies /api/ to backend)
ENV REACT_APP_API_URL=

COPY package.json ./
RUN npm install

COPY . .
RUN npm run build

# Serve with nginx
FROM nginx:alpine
COPY --from=build /app/build /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
