#!/bin/bash
# MedUnderwrite AI — EC2 First-Time Setup Script
# Owner: Persona B (Day 2 PM)
# TODO: implement per developer guide Section 4.6
#
# Steps:
#   1. Install Docker + Docker Compose on Amazon Linux 2
#   2. Add 2GB swap file (critical for t2.micro with 1GB RAM)
#   3. Clone GitHub repo
#   4. Copy .env.example to .env with placeholder message
#   5. docker-compose up -d
#   6. Print live URL at end

set -e

echo "🚀 MedUnderwrite AI — EC2 Setup"
echo "================================"

# TODO (Persona B): implement each step here

echo "✅ Setup complete. Access the app at: http://$(curl -s http://169.254.169.254/latest/meta-data/public-ipv4):4200"
