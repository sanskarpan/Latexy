#!/bin/bash

# Production Deployment Script for Latexy
# This script handles the complete deployment process

set -euo pipefail

# Configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
DEPLOY_ENV="${DEPLOY_ENV:-production}"
BACKUP_BEFORE_DEPLOY="${BACKUP_BEFORE_DEPLOY:-true}"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Function to log messages with colors
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
        *)
            echo -e "[${timestamp}] $level: $message"
            ;;
    esac
}

# Function to show usage
usage() {
    echo "Usage: $0 [OPTIONS]"
    echo ""
    echo "Options:"
    echo "  --env ENV                 Deployment environment (default: production)"
    echo "  --skip-backup            Skip database backup before deployment"
    echo "  --skip-build             Skip building Docker images"
    echo "  --skip-tests             Skip running tests"
    echo "  --rollback VERSION       Rollback to specific version"
    echo "  --dry-run                Show what would be deployed without executing"
    echo "  -h, --help               Show this help message"
    echo ""
    echo "Examples:"
    echo "  $0                       # Full production deployment"
    echo "  $0 --env staging         # Deploy to staging environment"
    echo "  $0 --skip-backup         # Deploy without backup"
    echo "  $0 --rollback v1.2.3     # Rollback to version v1.2.3"
}

# Function to check prerequisites
check_prerequisites() {
    log "INFO" "Checking deployment prerequisites..."
    
    local missing_tools=()
    
    # Check required tools
    for tool in docker docker-compose git; do
        if ! command -v "$tool" &> /dev/null; then
            missing_tools+=("$tool")
        fi
    done
    
    if [[ ${#missing_tools[@]} -gt 0 ]]; then
        log "ERROR" "Missing required tools: ${missing_tools[*]}"
        return 1
    fi
    
    # Check Docker daemon
    if ! docker info &> /dev/null; then
        log "ERROR" "Docker daemon is not running"
        return 1
    fi
    
    # Check environment files
    if [[ ! -f "$PROJECT_ROOT/.env.production" ]]; then
        log "ERROR" "Production environment file not found: .env.production"
        return 1
    fi
    
    # Check Docker Compose file
    if [[ ! -f "$PROJECT_ROOT/docker-compose.prod.yml" ]]; then
        log "ERROR" "Production Docker Compose file not found"
        return 1
    fi
    
    log "SUCCESS" "Prerequisites check passed"
    return 0
}

# Function to load environment variables
load_environment() {
    log "INFO" "Loading environment variables for $DEPLOY_ENV..."
    
    if [[ -f "$PROJECT_ROOT/.env.$DEPLOY_ENV" ]]; then
        set -a
        source "$PROJECT_ROOT/.env.$DEPLOY_ENV"
        set +a
        log "SUCCESS" "Environment variables loaded"
    else
        log "WARNING" "Environment file not found: .env.$DEPLOY_ENV"
    fi
}

# Function to get current version
get_current_version() {
    if [[ -f "$PROJECT_ROOT/VERSION" ]]; then
        cat "$PROJECT_ROOT/VERSION"
    else
        git describe --tags --always --dirty 2>/dev/null || echo "unknown"
    fi
}

# Function to create backup
create_backup() {
    if [[ "$BACKUP_BEFORE_DEPLOY" != "true" ]]; then
        log "INFO" "Skipping backup (disabled)"
        return 0
    fi
    
    log "INFO" "Creating backup before deployment..."
    
    if [[ -f "$PROJECT_ROOT/scripts/backup/database-backup.sh" ]]; then
        if bash "$PROJECT_ROOT/scripts/backup/database-backup.sh"; then
            log "SUCCESS" "Database backup completed"
        else
            log "ERROR" "Database backup failed"
            return 1
        fi
    else
        log "WARNING" "Database backup script not found"
    fi
    
    if [[ -f "$PROJECT_ROOT/scripts/backup/redis-backup.sh" ]]; then
        if bash "$PROJECT_ROOT/scripts/backup/redis-backup.sh"; then
            log "SUCCESS" "Redis backup completed"
        else
            log "WARNING" "Redis backup failed, continuing deployment"
        fi
    else
        log "WARNING" "Redis backup script not found"
    fi
}

# Function to run tests
run_tests() {
    log "INFO" "Running tests..."
    
    # Backend tests
    if [[ -f "$PROJECT_ROOT/backend/pytest.ini" ]]; then
        log "INFO" "Running backend tests..."
        cd "$PROJECT_ROOT/backend"
        if docker-compose -f ../docker-compose.yml run --rm backend pytest; then
            log "SUCCESS" "Backend tests passed"
        else
            log "ERROR" "Backend tests failed"
            return 1
        fi
    fi
    
    # Frontend tests
    if [[ -f "$PROJECT_ROOT/frontend/package.json" ]]; then
        log "INFO" "Running frontend tests..."
        cd "$PROJECT_ROOT/frontend"
        if npm test -- --watchAll=false; then
            log "SUCCESS" "Frontend tests passed"
        else
            log "ERROR" "Frontend tests failed"
            return 1
        fi
    fi
    
    cd "$PROJECT_ROOT"
}

# Function to build Docker images
build_images() {
    log "INFO" "Building Docker images..."
    
    local version
    version=$(get_current_version)
    
    # Build production images
    if docker-compose -f docker-compose.prod.yml build \
        --build-arg VERSION="$version" \
        --build-arg BUILD_DATE="$(date -u +'%Y-%m-%dT%H:%M:%SZ')" \
        --build-arg VCS_REF="$(git rev-parse HEAD 2>/dev/null || echo 'unknown')"; then
        log "SUCCESS" "Docker images built successfully"
    else
        log "ERROR" "Failed to build Docker images"
        return 1
    fi
    
    # Tag images with version
    docker tag latexy-frontend:latest "latexy-frontend:$version"
    docker tag latexy-backend:latest "latexy-backend:$version"
    
    log "SUCCESS" "Images tagged with version: $version"
}

# Function to deploy services
deploy_services() {
    local dry_run="${1:-false}"
    
    log "INFO" "Deploying services..."
    
    if [[ "$dry_run" == "true" ]]; then
        log "INFO" "DRY RUN: Would deploy the following services:"
        docker-compose -f docker-compose.prod.yml config --services
        return 0
    fi
    
    # Pull latest images (if using registry)
    # docker-compose -f docker-compose.prod.yml pull
    
    # Deploy with zero-downtime strategy
    log "INFO" "Starting new containers..."
    if docker-compose -f docker-compose.prod.yml up -d --remove-orphans; then
        log "SUCCESS" "Services deployed successfully"
    else
        log "ERROR" "Failed to deploy services"
        return 1
    fi
    
    # Wait for services to be healthy
    log "INFO" "Waiting for services to be healthy..."
    sleep 30
    
    # Check service health
    if check_service_health; then
        log "SUCCESS" "All services are healthy"
    else
        log "ERROR" "Some services are not healthy"
        return 1
    fi
}

# Function to check service health
check_service_health() {
    log "INFO" "Checking service health..."
    
    local max_attempts=30
    local attempt=1
    
    while [[ $attempt -le $max_attempts ]]; do
        log "INFO" "Health check attempt $attempt/$max_attempts"
        
        # Check backend health
        if curl -f -s "http://localhost:8000/health" > /dev/null; then
            log "SUCCESS" "Backend is healthy"
            break
        else
            log "WARNING" "Backend not ready yet..."
            sleep 10
            ((attempt++))
        fi
    done
    
    if [[ $attempt -gt $max_attempts ]]; then
        log "ERROR" "Backend health check failed"
        return 1
    fi
    
    # Check frontend (through nginx)
    if curl -f -s "http://localhost" > /dev/null; then
        log "SUCCESS" "Frontend is healthy"
    else
        log "WARNING" "Frontend health check failed"
    fi
    
    return 0
}

# Function to run database migrations
run_migrations() {
    log "INFO" "Running database migrations..."
    
    if docker-compose -f docker-compose.prod.yml exec -T backend alembic upgrade head; then
        log "SUCCESS" "Database migrations completed"
    else
        log "ERROR" "Database migrations failed"
        return 1
    fi
}

# Function to rollback deployment
rollback_deployment() {
    local version="$1"
    
    log "INFO" "Rolling back to version: $version"
    
    # Check if backup exists for rollback
    local backup_file="/opt/backups/database/latexy_backup_${version}.sql.gz"
    if [[ -f "$backup_file" ]]; then
        log "INFO" "Found backup for version $version, restoring database..."
        if bash "$PROJECT_ROOT/scripts/backup/restore-database.sh" -f "$backup_file"; then
            log "SUCCESS" "Database restored from backup"
        else
            log "ERROR" "Failed to restore database from backup"
            return 1
        fi
    else
        log "WARNING" "No backup found for version $version, skipping database restore"
    fi
    
    # Deploy previous version
    if docker-compose -f docker-compose.prod.yml down; then
        log "INFO" "Stopped current services"
    fi
    
    # Use previous images
    docker tag "latexy-frontend:$version" latexy-frontend:latest
    docker tag "latexy-backend:$version" latexy-backend:latest
    
    # Deploy
    if deploy_services; then
        log "SUCCESS" "Rollback completed successfully"
    else
        log "ERROR" "Rollback failed"
        return 1
    fi
}

# Function to cleanup old images
cleanup_old_images() {
    log "INFO" "Cleaning up old Docker images..."
    
    # Remove dangling images
    docker image prune -f
    
    # Keep only last 5 versions of each image
    for image in latexy-frontend latexy-backend; do
        docker images "$image" --format "table {{.Tag}}\t{{.ID}}" | \
        grep -v "latest" | \
        tail -n +6 | \
        awk '{print $2}' | \
        xargs -r docker rmi
    done
    
    log "SUCCESS" "Image cleanup completed"
}

# Function to send deployment notification
send_notification() {
    local status="$1"
    local version="$2"
    local message="$3"
    
    if [[ -n "${DEPLOYMENT_WEBHOOK_URL:-}" ]]; then
        curl -X POST "$DEPLOYMENT_WEBHOOK_URL" \
            -H "Content-Type: application/json" \
            -d "{
                \"status\": \"$status\",
                \"version\": \"$version\",
                \"environment\": \"$DEPLOY_ENV\",
                \"message\": \"$message\",
                \"timestamp\": \"$(date -u +'%Y-%m-%dT%H:%M:%SZ')\"
            }" \
            2>/dev/null || true
    fi
}

# Main deployment function
main() {
    local skip_backup=false
    local skip_build=false
    local skip_tests=false
    local rollback_version=""
    local dry_run=false
    
    # Parse command line arguments
    while [[ $# -gt 0 ]]; do
        case $1 in
            --env)
                DEPLOY_ENV="$2"
                shift 2
                ;;
            --skip-backup)
                skip_backup=true
                shift
                ;;
            --skip-build)
                skip_build=true
                shift
                ;;
            --skip-tests)
                skip_tests=true
                shift
                ;;
            --rollback)
                rollback_version="$2"
                shift 2
                ;;
            --dry-run)
                dry_run=true
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
    
    # Set backup flag
    if [[ "$skip_backup" == "true" ]]; then
        BACKUP_BEFORE_DEPLOY=false
    fi
    
    # Change to project root
    cd "$PROJECT_ROOT"
    
    # Get current version
    local version
    version=$(get_current_version)
    
    log "INFO" "=== Starting Latexy Deployment ==="
    log "INFO" "Environment: $DEPLOY_ENV"
    log "INFO" "Version: $version"
    log "INFO" "Dry Run: $dry_run"
    
    # Handle rollback
    if [[ -n "$rollback_version" ]]; then
        if rollback_deployment "$rollback_version"; then
            send_notification "success" "$rollback_version" "Rollback completed successfully"
            log "SUCCESS" "=== Rollback completed successfully ==="
        else
            send_notification "error" "$rollback_version" "Rollback failed"
            log "ERROR" "=== Rollback failed ==="
            exit 1
        fi
        return 0
    fi
    
    # Check prerequisites
    if ! check_prerequisites; then
        send_notification "error" "$version" "Prerequisites check failed"
        exit 1
    fi
    
    # Load environment
    load_environment
    
    # Create backup
    if [[ "$dry_run" != "true" ]]; then
        if ! create_backup; then
            send_notification "error" "$version" "Backup creation failed"
            exit 1
        fi
    fi
    
    # Run tests
    if [[ "$skip_tests" != "true" && "$dry_run" != "true" ]]; then
        if ! run_tests; then
            send_notification "error" "$version" "Tests failed"
            exit 1
        fi
    fi
    
    # Build images
    if [[ "$skip_build" != "true" && "$dry_run" != "true" ]]; then
        if ! build_images; then
            send_notification "error" "$version" "Image build failed"
            exit 1
        fi
    fi
    
    # Deploy services
    if ! deploy_services "$dry_run"; then
        send_notification "error" "$version" "Service deployment failed"
        exit 1
    fi
    
    # Run migrations
    if [[ "$dry_run" != "true" ]]; then
        if ! run_migrations; then
            send_notification "error" "$version" "Database migrations failed"
            exit 1
        fi
    fi
    
    # Cleanup
    if [[ "$dry_run" != "true" ]]; then
        cleanup_old_images
    fi
    
    # Send success notification
    send_notification "success" "$version" "Deployment completed successfully"
    
    log "SUCCESS" "=== Deployment completed successfully ==="
    log "INFO" "Version deployed: $version"
    log "INFO" "Environment: $DEPLOY_ENV"
}

# Run the main function
main "$@"

