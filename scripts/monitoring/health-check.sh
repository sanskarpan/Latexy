#!/bin/bash

# Health Check Script for Latexy Production
# This script monitors the health of all services and sends alerts

set -euo pipefail

# Configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
HEALTH_CHECK_TIMEOUT=30
ALERT_THRESHOLD=3  # Number of consecutive failures before alerting

# Load environment variables
if [ -f "$PROJECT_ROOT/.env.production" ]; then
    source "$PROJECT_ROOT/.env.production"
fi

# Service endpoints
BACKEND_URL="${BACKEND_URL:-http://localhost:8000}"
FRONTEND_URL="${FRONTEND_URL:-http://localhost}"
REDIS_HOST="${REDIS_HOST:-localhost}"
REDIS_PORT="${REDIS_PORT:-6379}"
POSTGRES_HOST="${POSTGRES_HOST:-localhost}"
POSTGRES_PORT="${POSTGRES_PORT:-5432}"

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

# Function to send alert
send_alert() {
    local service="$1"
    local status="$2"
    local message="$3"
    
    # Send to monitoring webhook
    if [[ -n "${MONITORING_WEBHOOK_URL:-}" ]]; then
        curl -X POST "$MONITORING_WEBHOOK_URL" \
            -H "Content-Type: application/json" \
            -d "{
                \"service\": \"$service\",
                \"status\": \"$status\",
                \"message\": \"$message\",
                \"timestamp\": \"$(date -u +'%Y-%m-%dT%H:%M:%SZ')\",
                \"environment\": \"${DEPLOY_ENV:-production}\"
            }" \
            --max-time 10 \
            2>/dev/null || log "WARNING" "Failed to send alert webhook"
    fi
    
    # Send to Slack if configured
    if [[ -n "${SLACK_WEBHOOK_URL:-}" ]]; then
        local color="danger"
        if [[ "$status" == "healthy" ]]; then
            color="good"
        elif [[ "$status" == "warning" ]]; then
            color="warning"
        fi
        
        curl -X POST "$SLACK_WEBHOOK_URL" \
            -H "Content-Type: application/json" \
            -d "{
                \"attachments\": [{
                    \"color\": \"$color\",
                    \"title\": \"Latexy Health Alert\",
                    \"fields\": [
                        {\"title\": \"Service\", \"value\": \"$service\", \"short\": true},
                        {\"title\": \"Status\", \"value\": \"$status\", \"short\": true},
                        {\"title\": \"Message\", \"value\": \"$message\", \"short\": false}
                    ],
                    \"ts\": $(date +%s)
                }]
            }" \
            --max-time 10 \
            2>/dev/null || log "WARNING" "Failed to send Slack alert"
    fi
}

# Function to check HTTP endpoint
check_http_endpoint() {
    local name="$1"
    local url="$2"
    local expected_status="${3:-200}"
    
    log "INFO" "Checking $name at $url"
    
    local response_code
    if response_code=$(curl -s -o /dev/null -w "%{http_code}" --max-time "$HEALTH_CHECK_TIMEOUT" "$url"); then
        if [[ "$response_code" == "$expected_status" ]]; then
            log "SUCCESS" "$name is healthy (HTTP $response_code)"
            return 0
        else
            log "ERROR" "$name returned HTTP $response_code (expected $expected_status)"
            return 1
        fi
    else
        log "ERROR" "$name is unreachable"
        return 1
    fi
}

# Function to check Redis
check_redis() {
    log "INFO" "Checking Redis at $REDIS_HOST:$REDIS_PORT"
    
    local redis_cmd="redis-cli -h $REDIS_HOST -p $REDIS_PORT"
    if [[ -n "${REDIS_PASSWORD:-}" ]]; then
        redis_cmd="$redis_cmd -a $REDIS_PASSWORD"
    fi
    
    if timeout "$HEALTH_CHECK_TIMEOUT" $redis_cmd ping > /dev/null 2>&1; then
        # Get Redis info
        local memory_usage
        memory_usage=$($redis_cmd INFO memory | grep "used_memory_human" | cut -d: -f2 | tr -d '\r')
        local connected_clients
        connected_clients=$($redis_cmd INFO clients | grep "connected_clients" | cut -d: -f2 | tr -d '\r')
        
        log "SUCCESS" "Redis is healthy (Memory: $memory_usage, Clients: $connected_clients)"
        return 0
    else
        log "ERROR" "Redis is unreachable or not responding"
        return 1
    fi
}

# Function to check PostgreSQL
check_postgres() {
    log "INFO" "Checking PostgreSQL at $POSTGRES_HOST:$POSTGRES_PORT"
    
    if [[ -z "${DATABASE_URL:-}" ]]; then
        log "WARNING" "DATABASE_URL not set, skipping PostgreSQL check"
        return 0
    fi
    
    if timeout "$HEALTH_CHECK_TIMEOUT" psql "$DATABASE_URL" -c "SELECT 1;" > /dev/null 2>&1; then
        # Get database info
        local db_size
        db_size=$(psql "$DATABASE_URL" -t -c "SELECT pg_size_pretty(pg_database_size(current_database()));" 2>/dev/null | xargs || echo "unknown")
        local connections
        connections=$(psql "$DATABASE_URL" -t -c "SELECT count(*) FROM pg_stat_activity;" 2>/dev/null | xargs || echo "unknown")
        
        log "SUCCESS" "PostgreSQL is healthy (Size: $db_size, Connections: $connections)"
        return 0
    else
        log "ERROR" "PostgreSQL is unreachable or not responding"
        return 1
    fi
}

# Function to check Docker containers
check_docker_containers() {
    log "INFO" "Checking Docker containers"
    
    if ! command -v docker &> /dev/null; then
        log "WARNING" "Docker not available, skipping container check"
        return 0
    fi
    
    local containers
    containers=$(docker ps --format "table {{.Names}}\t{{.Status}}" | grep -E "(latexy|frontend|backend|postgres|redis)" || true)
    
    if [[ -n "$containers" ]]; then
        log "INFO" "Running containers:"
        echo "$containers"
        
        # Check for unhealthy containers
        local unhealthy
        unhealthy=$(docker ps --filter "health=unhealthy" --format "{{.Names}}" | grep -E "(latexy|frontend|backend)" || true)
        
        if [[ -n "$unhealthy" ]]; then
            log "ERROR" "Unhealthy containers found: $unhealthy"
            return 1
        else
            log "SUCCESS" "All containers are healthy"
            return 0
        fi
    else
        log "WARNING" "No Latexy containers found running"
        return 1
    fi
}

# Function to check disk space
check_disk_space() {
    log "INFO" "Checking disk space"
    
    local usage
    usage=$(df -h / | awk 'NR==2 {print $5}' | sed 's/%//')
    
    if [[ "$usage" -gt 90 ]]; then
        log "ERROR" "Disk usage is critical: ${usage}%"
        return 1
    elif [[ "$usage" -gt 80 ]]; then
        log "WARNING" "Disk usage is high: ${usage}%"
        return 1
    else
        log "SUCCESS" "Disk usage is normal: ${usage}%"
        return 0
    fi
}

# Function to check memory usage
check_memory_usage() {
    log "INFO" "Checking memory usage"
    
    local memory_info
    memory_info=$(free -m | awk 'NR==2{printf "%.1f", $3*100/$2}')
    
    if (( $(echo "$memory_info > 90" | bc -l) )); then
        log "ERROR" "Memory usage is critical: ${memory_info}%"
        return 1
    elif (( $(echo "$memory_info > 80" | bc -l) )); then
        log "WARNING" "Memory usage is high: ${memory_info}%"
        return 1
    else
        log "SUCCESS" "Memory usage is normal: ${memory_info}%"
        return 0
    fi
}

# Function to check SSL certificate
check_ssl_certificate() {
    local domain="${SSL_DOMAIN:-localhost}"
    
    if [[ "$domain" == "localhost" ]]; then
        log "INFO" "Skipping SSL check for localhost"
        return 0
    fi
    
    log "INFO" "Checking SSL certificate for $domain"
    
    local expiry_date
    if expiry_date=$(echo | openssl s_client -servername "$domain" -connect "$domain:443" 2>/dev/null | openssl x509 -noout -dates | grep notAfter | cut -d= -f2); then
        local expiry_timestamp
        expiry_timestamp=$(date -d "$expiry_date" +%s)
        local current_timestamp
        current_timestamp=$(date +%s)
        local days_until_expiry
        days_until_expiry=$(( (expiry_timestamp - current_timestamp) / 86400 ))
        
        if [[ "$days_until_expiry" -lt 7 ]]; then
            log "ERROR" "SSL certificate expires in $days_until_expiry days"
            return 1
        elif [[ "$days_until_expiry" -lt 30 ]]; then
            log "WARNING" "SSL certificate expires in $days_until_expiry days"
            return 1
        else
            log "SUCCESS" "SSL certificate is valid (expires in $days_until_expiry days)"
            return 0
        fi
    else
        log "ERROR" "Failed to check SSL certificate"
        return 1
    fi
}

# Function to check application-specific health
check_application_health() {
    log "INFO" "Checking application-specific health"
    
    # Check backend API health endpoint
    if ! check_http_endpoint "Backend API" "$BACKEND_URL/health"; then
        return 1
    fi
    
    # Check job system health
    if ! check_http_endpoint "Job System" "$BACKEND_URL/jobs/system/health"; then
        return 1
    fi
    
    # Check if we can compile a simple LaTeX document
    local test_payload='{"latex_content": "\\documentclass{article}\\begin{document}Hello World\\end{document}", "optimization_type": "none"}'
    local compile_response
    if compile_response=$(curl -s -X POST "$BACKEND_URL/compile" \
        -H "Content-Type: application/json" \
        -d "$test_payload" \
        --max-time 60); then
        
        if echo "$compile_response" | grep -q '"status":"success"'; then
            log "SUCCESS" "LaTeX compilation is working"
        else
            log "WARNING" "LaTeX compilation may have issues"
        fi
    else
        log "WARNING" "Failed to test LaTeX compilation"
    fi
    
    return 0
}

# Function to generate health report
generate_health_report() {
    local overall_status="healthy"
    local failed_checks=()
    local warning_checks=()
    
    log "INFO" "=== Latexy Health Check Report ==="
    
    # Run all health checks
    local checks=(
        "check_http_endpoint Frontend $FRONTEND_URL"
        "check_http_endpoint Backend $BACKEND_URL/health"
        "check_redis"
        "check_postgres"
        "check_docker_containers"
        "check_disk_space"
        "check_memory_usage"
        "check_ssl_certificate"
        "check_application_health"
    )
    
    for check in "${checks[@]}"; do
        local check_name
        check_name=$(echo "$check" | awk '{print $1}' | sed 's/check_//')
        
        if eval "$check"; then
            echo "✅ $check_name"
        else
            echo "❌ $check_name"
            failed_checks+=("$check_name")
            overall_status="unhealthy"
        fi
    done
    
    # Generate summary
    echo ""
    log "INFO" "=== Health Check Summary ==="
    log "INFO" "Overall Status: $overall_status"
    
    if [[ ${#failed_checks[@]} -gt 0 ]]; then
        log "ERROR" "Failed Checks: ${failed_checks[*]}"
        send_alert "latexy-system" "unhealthy" "Health check failed for: ${failed_checks[*]}"
    else
        log "SUCCESS" "All health checks passed"
        send_alert "latexy-system" "healthy" "All health checks passed successfully"
    fi
    
    # Return appropriate exit code
    if [[ "$overall_status" == "healthy" ]]; then
        return 0
    else
        return 1
    fi
}

# Function to show usage
usage() {
    echo "Usage: $0 [OPTIONS]"
    echo ""
    echo "Options:"
    echo "  --service SERVICE    Check specific service only"
    echo "  --json              Output results in JSON format"
    echo "  --quiet             Suppress output (exit code only)"
    echo "  -h, --help          Show this help message"
    echo ""
    echo "Services:"
    echo "  frontend            Frontend application"
    echo "  backend             Backend API"
    echo "  redis               Redis cache"
    echo "  postgres            PostgreSQL database"
    echo "  docker              Docker containers"
    echo "  system              System resources"
    echo "  ssl                 SSL certificate"
    echo "  application         Application-specific checks"
}

# Main execution
main() {
    local specific_service=""
    local json_output=false
    local quiet=false
    
    # Parse command line arguments
    while [[ $# -gt 0 ]]; do
        case $1 in
            --service)
                specific_service="$2"
                shift 2
                ;;
            --json)
                json_output=true
                shift
                ;;
            --quiet)
                quiet=true
                shift
                ;;
            -h|--help)
                usage
                exit 0
                ;;
            *)
                log "ERROR" "Unknown option: $1"
                usage
                exit 1
                ;;
        esac
    done
    
    # Redirect output if quiet mode
    if [[ "$quiet" == "true" ]]; then
        exec > /dev/null 2>&1
    fi
    
    # Check specific service if requested
    if [[ -n "$specific_service" ]]; then
        case "$specific_service" in
            frontend)
                check_http_endpoint "Frontend" "$FRONTEND_URL"
                ;;
            backend)
                check_http_endpoint "Backend" "$BACKEND_URL/health"
                ;;
            redis)
                check_redis
                ;;
            postgres)
                check_postgres
                ;;
            docker)
                check_docker_containers
                ;;
            system)
                check_disk_space && check_memory_usage
                ;;
            ssl)
                check_ssl_certificate
                ;;
            application)
                check_application_health
                ;;
            *)
                log "ERROR" "Unknown service: $specific_service"
                exit 1
                ;;
        esac
    else
        # Run full health check
        generate_health_report
    fi
}

# Run the main function
main "$@"
