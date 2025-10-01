# Latexy Production Deployment Guide

This guide covers the complete production deployment of Latexy, including Docker Compose, Kubernetes, monitoring, and CI/CD setup.

## 📋 Prerequisites

### System Requirements
- **CPU**: Minimum 4 cores (8 cores recommended)
- **Memory**: Minimum 8GB RAM (16GB recommended)
- **Storage**: Minimum 50GB SSD (100GB recommended)
- **Network**: Stable internet connection with sufficient bandwidth

### Software Requirements
- Docker 20.10+ and Docker Compose 2.0+
- Kubernetes 1.24+ (for K8s deployment)
- kubectl configured for your cluster
- Git
- OpenSSL (for SSL certificates)

### External Services
- Domain name with DNS control
- SSL certificate (Let's Encrypt recommended)
- Email service (SMTP)
- Cloud storage (AWS S3 for backups)
- Monitoring service (optional)

## 🚀 Quick Start (Docker Compose)

### 1. Clone and Setup
```bash
git clone <your-repo-url>
cd Latexy
cp .env.production .env.prod
```

### 2. Configure Environment
Edit `.env.prod` with your production values:
```bash
# Critical settings to change:
DATABASE_URL=postgresql://user:pass@postgres:5432/latexy_prod
REDIS_URL=redis://:password@redis:6379/0
OPENAI_API_KEY=your_openai_key
BETTER_AUTH_SECRET=your_32_char_secret
RAZORPAY_KEY_ID=your_razorpay_key
# ... (see .env.production for all settings)
```

### 3. Deploy
```bash
# Build and deploy
./scripts/deploy/deploy.sh

# Or manually:
docker-compose -f docker-compose.prod.yml up -d
```

### 4. Initialize Database
```bash
# Run migrations
docker-compose -f docker-compose.prod.yml exec backend alembic upgrade head
```

### 5. Verify Deployment
```bash
# Check health
curl http://localhost/health

# View logs
docker-compose -f docker-compose.prod.yml logs -f
```

## ☸️ Kubernetes Deployment

### 1. Prepare Cluster
```bash
# Create namespace and secrets
kubectl apply -f k8s/namespace.yaml

# Update secrets in k8s/namespace.yaml with base64 encoded values:
echo -n "your_database_url" | base64
echo -n "your_redis_url" | base64
# ... etc
```

### 2. Deploy Services
```bash
# Full deployment
./k8s/deploy.sh

# Or step by step:
./k8s/deploy.sh database
./k8s/deploy.sh redis
./k8s/deploy.sh backend
./k8s/deploy.sh frontend
./k8s/deploy.sh celery
./k8s/deploy.sh nginx
./k8s/deploy.sh monitoring
```

### 3. Check Status
```bash
./k8s/deploy.sh status
./k8s/deploy.sh health
./k8s/deploy.sh urls
```

## 🔧 Configuration

### SSL/TLS Setup
```bash
# Generate self-signed certificate (development)
openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
  -keyout nginx/ssl/latexy.key \
  -out nginx/ssl/latexy.crt

# For production, use Let's Encrypt:
certbot certonly --webroot -w /var/www/certbot \
  -d your-domain.com -d www.your-domain.com
```

### Database Setup
```bash
# Create production database
createdb latexy_prod

# Run migrations
alembic upgrade head

# Create admin user (optional)
python scripts/create_admin_user.py
```

### Monitoring Configuration
```bash
# Access Grafana
kubectl port-forward -n latexy service/grafana-service 3000:3000
# Visit http://localhost:3000 (admin/grafana123)

# Access Prometheus
kubectl port-forward -n latexy service/prometheus-service 9090:9090
# Visit http://localhost:9090

# Access Flower (Celery monitoring)
kubectl port-forward -n latexy service/flower-service 5555:5555
# Visit http://localhost:5555
```

## 🔄 CI/CD Pipeline

### GitHub Actions Setup
1. Add repository secrets:
   ```
   DOCKER_USERNAME
   DOCKER_PASSWORD
   KUBE_CONFIG_DATA (base64 encoded kubeconfig)
   PRODUCTION_ENV (base64 encoded .env.prod)
   ```

2. Push to trigger deployment:
   ```bash
   git push origin main
   ```

### Manual Deployment
```bash
# Build and push images
docker build -t your-registry/latexy-backend:latest -f backend/Dockerfile.prod backend/
docker build -t your-registry/latexy-frontend:latest -f frontend/Dockerfile.prod frontend/
docker push your-registry/latexy-backend:latest
docker push your-registry/latexy-frontend:latest

# Deploy to Kubernetes
./k8s/deploy.sh
```

## 📊 Monitoring & Observability

### Health Checks
```bash
# System health
./scripts/monitoring/health-check.sh

# Specific service
./scripts/monitoring/health-check.sh --service backend

# Continuous monitoring
watch -n 30 './scripts/monitoring/health-check.sh --quiet'
```

### Log Management
```bash
# Collect logs
./scripts/monitoring/log-aggregator.sh

# Analyze logs
./scripts/monitoring/log-aggregator.sh --analyze-only

# Rotate logs
./scripts/monitoring/log-aggregator.sh --rotate-only
```

### Metrics & Alerts
- **Grafana Dashboard**: Application metrics, system resources
- **Prometheus Alerts**: CPU, memory, disk usage, service availability
- **Custom Metrics**: Job queue length, compilation success rate, user activity

## 💾 Backup & Recovery

### Automated Backups
```bash
# Setup cron job for daily backups
echo "0 2 * * * /opt/latexy/scripts/backup/database-backup.sh" | crontab -
echo "0 3 * * * /opt/latexy/scripts/backup/redis-backup.sh" | crontab -
```

### Manual Backup
```bash
# Database backup
./scripts/backup/database-backup.sh

# Redis backup
./scripts/backup/redis-backup.sh
```

### Restore from Backup
```bash
# List available backups
./scripts/backup/restore-database.sh --list

# Restore latest backup
./scripts/backup/restore-database.sh --latest

# Restore specific backup
./scripts/backup/restore-database.sh -f backup_20241201_120000.sql.gz
```

## 🔒 Security Considerations

### Environment Variables
- Use strong, unique passwords for all services
- Rotate API keys regularly
- Store secrets in secure key management systems
- Use environment-specific configurations

### Network Security
- Configure firewall rules (ports 80, 443 only)
- Use VPC/private networks for internal communication
- Enable SSL/TLS for all external connections
- Implement rate limiting and DDoS protection

### Application Security
- Regular security updates for all dependencies
- Implement proper authentication and authorization
- Use HTTPS everywhere
- Regular security audits and penetration testing

## 🚨 Troubleshooting

### Common Issues

#### Services Not Starting
```bash
# Check logs
docker-compose -f docker-compose.prod.yml logs service-name
kubectl logs -n latexy deployment/service-name

# Check resource usage
docker stats
kubectl top pods -n latexy
```

#### Database Connection Issues
```bash
# Test connection
psql $DATABASE_URL -c "SELECT 1;"

# Check PostgreSQL logs
kubectl logs -n latexy deployment/postgres
```

#### Redis Connection Issues
```bash
# Test Redis
redis-cli -h redis-host -p 6379 ping

# Check Redis logs
kubectl logs -n latexy deployment/redis
```

#### High Memory Usage
```bash
# Check memory usage
free -h
docker stats --no-stream

# Restart services if needed
docker-compose -f docker-compose.prod.yml restart
kubectl rollout restart deployment/service-name -n latexy
```

### Performance Optimization

#### Database Optimization
```sql
-- Add indexes for better performance
CREATE INDEX CONCURRENTLY idx_jobs_status ON jobs(status);
CREATE INDEX CONCURRENTLY idx_jobs_created_at ON jobs(created_at);
CREATE INDEX CONCURRENTLY idx_user_api_keys_user_id ON user_api_keys(user_id);
```

#### Redis Optimization
```bash
# Configure Redis for production
redis-cli CONFIG SET maxmemory-policy allkeys-lru
redis-cli CONFIG SET save "900 1 300 10 60 10000"
```

#### Application Optimization
- Enable HTTP/2 in Nginx
- Configure proper caching headers
- Use CDN for static assets
- Optimize Docker images for smaller size

## 📈 Scaling

### Horizontal Scaling
```bash
# Scale backend replicas
kubectl scale deployment latexy-backend --replicas=5 -n latexy

# Scale Celery workers
kubectl scale deployment celery-worker --replicas=10 -n latexy

# Scale frontend replicas
kubectl scale deployment latexy-frontend --replicas=3 -n latexy
```

### Vertical Scaling
```yaml
# Update resource limits in deployment manifests
resources:
  requests:
    memory: "1Gi"
    cpu: "500m"
  limits:
    memory: "2Gi"
    cpu: "1000m"
```

### Database Scaling
- Use read replicas for read-heavy workloads
- Implement connection pooling
- Consider database sharding for very large datasets

## 🔄 Maintenance

### Regular Tasks
- **Daily**: Check system health, review logs
- **Weekly**: Update dependencies, security patches
- **Monthly**: Review metrics, optimize performance
- **Quarterly**: Security audit, disaster recovery testing

### Update Procedure
```bash
# 1. Backup current state
./scripts/backup/database-backup.sh

# 2. Update code
git pull origin main

# 3. Build new images
docker-compose -f docker-compose.prod.yml build

# 4. Deploy with zero downtime
./scripts/deploy/deploy.sh

# 5. Run migrations
./scripts/deploy/deploy.sh migrate

# 6. Verify deployment
./scripts/monitoring/health-check.sh
```

### Rollback Procedure
```bash
# Rollback to previous version
./scripts/deploy/deploy.sh --rollback v1.0.0

# Or using Kubernetes
kubectl rollout undo deployment/latexy-backend -n latexy
```

## 📞 Support

### Monitoring Alerts
- Configure alerts for critical metrics
- Set up notification channels (Slack, email, PagerDuty)
- Document incident response procedures

### Log Analysis
- Centralized logging with ELK stack or similar
- Log retention policies
- Automated log analysis for error patterns

### Performance Monitoring
- Application Performance Monitoring (APM)
- Real User Monitoring (RUM)
- Synthetic monitoring for critical user journeys

---

For additional support or questions, please refer to the project documentation or contact the development team.

