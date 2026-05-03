#!/bin/bash

echo "========================================"
echo "🔍 DIAGNÓSTICO RED + DOCKER + SKAFFOLD"
echo "========================================"

echo ""
echo "🧭 1. INFO BÁSICA"
echo "----------------------------------------"
hostname
uname -a

echo ""
echo "🌐 2. DNS"
echo "----------------------------------------"
cat /etc/resolv.conf

echo ""
echo "🌍 3. RESOLUCIÓN DNS"
echo "----------------------------------------"
getent hosts registry-1.docker.io
getent hosts docker-images-prod.6aa30f8b08e16409b46e0173d6de2f56.r2.cloudflarestorage.com

echo ""
echo "📡 4. TEST HTTP DOCKER HUB"
echo "----------------------------------------"
curl -s -o /dev/null -w "HTTP_CODE=%{http_code}\n" https://registry-1.docker.io/v2/

echo ""
echo "📡 5. TEST CLOUDLFARE R2"
echo "----------------------------------------"
curl -v --max-time 5 https://docker-images-prod.6aa30f8b08e16409b46e0173d6de2f56.r2.cloudflarestorage.com 2>&1 | grep -E "Connected|refused|timed out|HTTP"

echo ""
echo "📡 6. TEST DIRECTO IP CLOUDLFARE"
echo "----------------------------------------"
curl -v --max-time 5 https://172.64.66.1 2>&1 | grep -E "Connected|refused|timed out"

echo ""
echo "🌐 7. IPv4 vs IPv6"
echo "----------------------------------------"
echo "IPv6 status:"
sysctl net.ipv6.conf.all.disable_ipv6

echo ""
echo "🧭 8. ROUTING"
echo "----------------------------------------"
ip route

echo ""
echo "🛰️ 9. TRACEROUTE (Cloudflare)"
echo "----------------------------------------"
traceroute -n -w 1 -q 1 172.64.66.1 || echo "traceroute no disponible"

echo ""
echo "🔥 10. FIREWALL"
echo "----------------------------------------"
sudo iptables -L -n | head -20
sudo ufw status 2>/dev/null || echo "ufw no instalado"

echo ""
echo "🐳 11. DOCKER"
echo "----------------------------------------"
docker version 2>/dev/null || echo "Docker no disponible"

echo ""
echo "🐳 12. DOCKER PULL TEST"
echo "----------------------------------------"
docker pull nginx:1.25-alpine 2>&1 | tail -10

echo ""
echo "🧠 13. CHECK IPv6 PRIORITY"
echo "----------------------------------------"
grep -E "^precedence ::ffff:0:0/96" /etc/gai.conf || echo "IPv4 NO priorizado"

echo ""
echo "========================================"
echo "✅ FIN DIAGNÓSTICO"
echo "========================================"
