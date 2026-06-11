FROM node:22-alpine

WORKDIR /app

ENV NODE_ENV=production

COPY package.json server.mjs ./
COPY index.html style.css ./
COPY data ./data
COPY js ./js
COPY assets ./assets

EXPOSE 8080

CMD ["node", "server.mjs"]
