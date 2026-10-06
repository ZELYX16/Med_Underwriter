# MedUnderwrite AI — Frontend Dockerfile (Multi-stage)
# Owner: Persona B (Day 2 PM)
# TODO: implement per developer guide Section 4.6

# Stage 1: Build Angular app
FROM node:20-alpine AS build
WORKDIR /app
# TODO: COPY package.json, npm install, ng build --configuration production

# Stage 2: Serve with Nginx
FROM nginx:alpine
# TODO: COPY --from=build /app/dist/medunderwrite-ai /usr/share/nginx/html
# TODO: COPY nginx.conf /etc/nginx/nginx.conf
EXPOSE 80
