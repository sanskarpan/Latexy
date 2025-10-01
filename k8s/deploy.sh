#!/bin/bash

# Kubernetes Deployment Script for Latexy
# This script deploys the entire Latexy application to Kubernetes

set -euo pipefail

# Configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NAMESPACE="latexy"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Function to log messages
log() {
    local level="$1"
    shift
    local message="$*"
    local timestamp=$(date '+%Y-%m-%d %H:%M:%S')
    
    case "$level" in
        "INFO")
            echo -e "${BLUE}[${timestamp}] INFO:${NC} $message"
            ;;
        "SUCCESS")
            echo -e "${GREEN}[${timestamp}] SUCCESS:${NC} $message"
            ;;
        "WARNING")
            echo -e "${YELLOW}[${timestamp}] WARNING:${NC} $message"
            ;;
        "ERROR")
            echo -e "${RED}[${timestamp}] ERROR:${NC} $message"
            ;;
    esac
}

# Function to check prerequisites
check_prerequisites() {
    log "INFO" "Checking Kubernetes deployment prerequisites..."
    
    # Check kubectl
    if ! command -v kubectl &> /dev/null; then
        log "ERROR" "kubectl is not installed or not in PATH"
        return 1
    fi
    
    # Check cluster connection
    if ! kubectl cluster-info &> /dev/null; then
        log "ERROR" "Cannot connect to Kubernetes cluster"
        return 1
    fi
    
    # Check if we can create resources
    if ! kubectl auth can-i create deployments --namespace="$NAMESPACE" &> /dev/null; then
        log "ERROR" "Insufficient permissions to create deployments in namespace $NAMESPACE"
        return 1
    fi
    
    log "SUCCESS" "Prerequisites check passed"
    return 0
}

# Function to create namespace and secrets
setup_namespace() {
    log "INFO" "Setting up namespace and secrets..."
    
    # Apply namespace and secrets
    kubectl apply -f "$SCRIPT_DIR/namespace.yaml"
    
    # Wait for namespace to be ready
    kubectl wait --for=condition=Ready namespace/"$NAMESPACE" --timeout=60s
    
    log "SUCCESS" "Namespace and secrets configured"
}

# Function to deploy database
deploy_database() {
    log "INFO" "Deploying PostgreSQL database..."
    
    kubectl apply -f "$SCRIPT_DIR/database/postgres.yaml"
    
    # Wait for PostgreSQL to be ready
    log "INFO" "Waiting for PostgreSQL to be ready..."
    kubectl wait --for=condition=Ready pod -l app=postgres -n "$NAMESPACE" --timeout=300s
    
    log "SUCCESS" "PostgreSQL deployed successfully"
}

# Function to deploy Redis
deploy_redis() {
    log "INFO" "Deploying Redis cache..."
    
    kubectl apply -f "$SCRIPT_DIR/redis/redis.yaml"
    
    # Wait for Redis to be ready
    log "INFO" "Waiting for Redis to be ready..."
    kubectl wait --for=condition=Ready pod -l app=redis -n "$NAMESPACE" --timeout=300s
    
    log "SUCCESS" "Redis deployed successfully"
}

# Function to deploy backend
deploy_backend() {
    log "INFO" "Deploying Latexy backend..."
    
    kubectl apply -f "$SCRIPT_DIR/backend/deployment.yaml"
    
    # Wait for backend to be ready
    log "INFO" "Waiting for backend to be ready..."
    kubectl wait --for=condition=Ready pod -l app=latexy-backend -n "$NAMESPACE" --timeout=300s
    
    log "SUCCESS" "Backend deployed successfully"
}

# Function to deploy frontend
deploy_frontend() {
    log "INFO" "Deploying Latexy frontend..."
    
    kubectl apply -f "$SCRIPT_DIR/frontend/deployment.yaml"
    
    # Wait for frontend to be ready
    log "INFO" "Waiting for frontend to be ready..."
    kubectl wait --for=condition=Ready pod -l app=latexy-frontend -n "$NAMESPACE" --timeout=300s
    
    log "SUCCESS" "Frontend deployed successfully"
}

# Function to deploy Celery workers
deploy_celery() {
    log "INFO" "Deploying Celery workers..."
    
    kubectl apply -f "$SCRIPT_DIR/celery/celery-worker.yaml"
    
    # Wait for workers to be ready
    log "INFO" "Waiting for Celery workers to be ready..."
    kubectl wait --for=condition=Ready pod -l app=celery-worker -n "$NAMESPACE" --timeout=300s
    
    log "SUCCESS" "Celery workers deployed successfully"
}

# Function to deploy Nginx
deploy_nginx() {
    log "INFO" "Deploying Nginx proxy..."
    
    kubectl apply -f "$SCRIPT_DIR/nginx/nginx.yaml"
    
    # Wait for Nginx to be ready
    log "INFO" "Waiting for Nginx to be ready..."
    kubectl wait --for=condition=Ready pod -l app=nginx -n "$NAMESPACE" --timeout=300s
    
    log "SUCCESS" "Nginx deployed successfully"
}

# Function to deploy monitoring
deploy_monitoring() {
    log "INFO" "Deploying monitoring stack..."
    
    # Deploy Prometheus
    kubectl apply -f "$SCRIPT_DIR/monitoring/prometheus.yaml"
    
    # Deploy Grafana
    kubectl apply -f "$SCRIPT_DIR/monitoring/grafana.yaml"
    
    # Wait for monitoring to be ready
    log "INFO" "Waiting for monitoring stack to be ready..."
    kubectl wait --for=condition=Ready pod -l app=prometheus -n "$NAMESPACE" --timeout=300s
    kubectl wait --for=condition=Ready pod -l app=grafana -n "$NAMESPACE" --timeout=300s
    
    log "SUCCESS" "Monitoring stack deployed successfully"
}

# Function to run database migrations
run_migrations() {
    log "INFO" "Running database migrations..."
    
    # Get backend pod name
    local backend_pod
    backend_pod=$(kubectl get pods -n "$NAMESPACE" -l app=latexy-backend -o jsonpath='{.items[0].metadata.name}')
    
    if [[ -z "$backend_pod" ]]; then
        log "ERROR" "No backend pod found"
        return 1
    fi
    
    # Run migrations
    if kubectl exec -n "$NAMESPACE" "$backend_pod" -- alembic upgrade head; then
        log "SUCCESS" "Database migrations completed"
    else
        log "ERROR" "Database migrations failed"
        return 1
    fi
}

# Function to check deployment health
check_deployment_health() {
    log "INFO" "Checking deployment health..."
    
    # Check all deployments
    local deployments=(
        "postgres"
        "redis"
        "latexy-backend"
        "latexy-frontend"
        "celery-worker"
        "celery-beat"
        "flower"
        "nginx"
        "prometheus"
        "grafana"
    )
    
    local failed_deployments=()
    
    for deployment in "${deployments[@]}"; do
        if kubectl get deployment "$deployment" -n "$NAMESPACE" &> /dev/null; then
            local ready_replicas
            ready_replicas=$(kubectl get deployment "$deployment" -n "$NAMESPACE" -o jsonpath='{.status.readyReplicas}' 2>/dev/null || echo "0")
            local desired_replicas
            desired_replicas=$(kubectl get deployment "$deployment" -n "$NAMESPACE" -o jsonpath='{.spec.replicas}' 2>/dev/null || echo "1")
            
            if [[ "$ready_replicas" == "$desired_replicas" ]]; then
                log "SUCCESS" "$deployment: $ready_replicas/$desired_replicas replicas ready"
            else
                log "ERROR" "$deployment: $ready_replicas/$desired_replicas replicas ready"
                failed_deployments+=("$deployment")
            fi
        else
            log "WARNING" "$deployment: deployment not found"
        fi
    done
    
    if [[ ${#failed_deployments[@]} -eq 0 ]]; then
        log "SUCCESS" "All deployments are healthy"
        return 0
    else
        log "ERROR" "Failed deployments: ${failed_deployments[*]}"
        return 1
    fi
}

# Function to get service URLs
get_service_urls() {
    log "INFO" "Getting service URLs..."
    
    # Get LoadBalancer IP for Nginx
    local nginx_ip
    nginx_ip=$(kubectl get service nginx-service -n "$NAMESPACE" -o jsonpath='{.status.loadBalancer.ingress[0].ip}' 2>/dev/null || echo "")
    
    if [[ -z "$nginx_ip" ]]; then
        nginx_ip=$(kubectl get service nginx-service -n "$NAMESPACE" -o jsonpath='{.status.loadBalancer.ingress[0].hostname}' 2>/dev/null || echo "")
    fi
    
    if [[ -n "$nginx_ip" ]]; then
        log "SUCCESS" "Application URL: http://$nginx_ip"
        log "SUCCESS" "Flower URL: http://$nginx_ip/flower/"
    else
        log "INFO" "LoadBalancer IP not yet assigned. Use port-forward to access services:"
        log "INFO" "kubectl port-forward -n $NAMESPACE service/nginx-service 8080:80"
        log "INFO" "Then access: http://localhost:8080"
    fi
    
    # Grafana access
    log "INFO" "Grafana access:"
    log "INFO" "kubectl port-forward -n $NAMESPACE service/grafana-service 3000:3000"
    log "INFO" "Then access: http://localhost:3000 (admin/grafana123)"
    
    # Prometheus access
    log "INFO" "Prometheus access:"
    log "INFO" "kubectl port-forward -n $NAMESPACE service/prometheus-service 9090:9090"
    log "INFO" "Then access: http://localhost:9090"
}

# Function to show deployment status
show_deployment_status() {
    log "INFO" "=== Deployment Status ==="
    
    echo ""
    log "INFO" "Pods:"
    kubectl get pods -n "$NAMESPACE" -o wide
    
    echo ""
    log "INFO" "Services:"
    kubectl get services -n "$NAMESPACE"
    
    echo ""
    log "INFO" "Deployments:"
    kubectl get deployments -n "$NAMESPACE"
    
    echo ""
    log "INFO" "PersistentVolumeClaims:"
    kubectl get pvc -n "$NAMESPACE"
}

# Function to cleanup deployment
cleanup_deployment() {
    log "WARNING" "Cleaning up Latexy deployment..."
    
    read -p "Are you sure you want to delete the entire Latexy deployment? (yes/no): " -r
    if [[ ! $REPLY =~ ^[Yy][Ee][Ss]$ ]]; then
        log "INFO" "Cleanup cancelled"
        return 0
    fi
    
    # Delete all resources in namespace
    kubectl delete namespace "$NAMESPACE" --ignore-not-found=true
    
    log "SUCCESS" "Deployment cleaned up"
}

# Function to show usage
usage() {
    echo "Usage: $0 [COMMAND]"
    echo ""
    echo "Commands:"
    echo "  deploy      Deploy the entire Latexy application (default)"
    echo "  status      Show deployment status"
    echo "  health      Check deployment health"
    echo "  urls        Show service URLs"
    echo "  cleanup     Remove the entire deployment"
    echo "  migrate     Run database migrations only"
    echo ""
    echo "Component-specific deployments:"
    echo "  database    Deploy PostgreSQL only"
    echo "  redis       Deploy Redis only"
    echo "  backend     Deploy backend only"
    echo "  frontend    Deploy frontend only"
    echo "  celery      Deploy Celery workers only"
    echo "  nginx       Deploy Nginx only"
    echo "  monitoring  Deploy monitoring stack only"
    echo ""
    echo "Examples:"
    echo "  $0                    # Full deployment"
    echo "  $0 deploy             # Full deployment"
    echo "  $0 status             # Show status"
    echo "  $0 backend            # Deploy backend only"
}

# Main execution
main() {
    local command="${1:-deploy}"
    
    case "$command" in
        "deploy")
            log "INFO" "=== Starting Latexy Kubernetes Deployment ==="
            
            if ! check_prerequisites; then
                exit 1
            fi
            
            setup_namespace
            deploy_database
            deploy_redis
            deploy_backend
            deploy_frontend
            deploy_celery
            deploy_nginx
            deploy_monitoring
            
            # Wait a bit for services to stabilize
            sleep 30
            
            run_migrations
            
            if check_deployment_health; then
                log "SUCCESS" "=== Deployment completed successfully ==="
                get_service_urls
            else
                log "ERROR" "=== Deployment completed with issues ==="
                show_deployment_status
                exit 1
            fi
            ;;
        "status")
            show_deployment_status
            ;;
        "health")
            check_deployment_health
            ;;
        "urls")
            get_service_urls
            ;;
        "cleanup")
            cleanup_deployment
            ;;
        "migrate")
            run_migrations
            ;;
        "database")
            setup_namespace
            deploy_database
            ;;
        "redis")
            setup_namespace
            deploy_redis
            ;;
        "backend")
            setup_namespace
            deploy_backend
            ;;
        "frontend")
            setup_namespace
            deploy_frontend
            ;;
        "celery")
            setup_namespace
            deploy_celery
            ;;
        "nginx")
            setup_namespace
            deploy_nginx
            ;;
        "monitoring")
            setup_namespace
            deploy_monitoring
            ;;
        "-h"|"--help"|"help")
            usage
            exit 0
            ;;
        *)
            log "ERROR" "Unknown command: $command"
            usage
            exit 1
            ;;
    esac
}

# Run the main function
main "$@"

