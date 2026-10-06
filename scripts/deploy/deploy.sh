#!/bin/bash

# Production Deployment Script for Latexy
# This script handles the complete deployment process

set -euo pipefail

# Configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
DEPLOY_ENV="${DEPLOY_ENV:-production}"
BACKUP_BEFORE_DEPLOY="${BACKUP_BEFORE_DEPLOY:-true}"
# Must match LATEXY_IMAGE_PREFIX in docker-compose.prod.yml
IMAGE_PREFIX="${LATEXY_IMAGE_PREFIX:-ghcr.io/sanskarpan}"
# Must match PORT in backend/Dockerfile.prod / docker-compose.prod.yml
BACKEND_PORT="${BACKEND_PORT:-8030}"

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
    local timestamp
    timestamp=$(date '+%Y-%m-%d %H:%M:%S')
    
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
        # DEPLOY_ENV is the selected environment name; the file is existence-checked above.
        # shellcheck disable=SC1090
        source "$PROJECT_ROOT/.env.$DEPLOY_ENV"
        set +a
        log "SUCCESS" "Environment variables loaded"
    else
        log "WARNING" "Environment file not found: .env.$DEPLOY_ENV"
    fi
}

# Function to get current version
get_current_version() {
    local exact_tag
    exact_tag=$(git describe --exact-match --tags HEAD 2>/dev/null || true)

    # A deploy must identify a clean immutable checkout.  Do not let a stale
    # VERSION file or a `git describe` string such as v1.2.3-4-gabc become an
    # image tag that does not correspond to a published release.
    if [[ -n "$(git status --porcelain=v1 --untracked-files=all)" ]]; then
        log "ERROR" "Refusing to deploy a dirty checkout; commit or remove local changes first"
        return 1
    fi

    if [[ "$exact_tag" =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
        printf '%s\n' "$exact_tag"
        return 0
    fi

    printf 'sha-%s\n' "$(git rev-parse --verify HEAD)"
}

# Compose image tags must identify one release or source revision.  In
# particular, --skip-build is never allowed to fall back to an unset value or
# to the mutable :latest tag.
validate_image_version() {
    local version="$1"
    if [[ ! "$version" =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ && ! "$version" =~ ^sha-[0-9a-fA-F]{7,64}$ ]]; then
        log "ERROR" "LATEXY_VERSION must be a vX.Y.Z release tag or sha-<commit> tag: $version"
        return 1
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

    # Compose's image keys are exact revision tags. Set the same revision for
    # the build, migration container, and application rollout; never retag
    # through a mutable :latest alias.
    LATEXY_VERSION="$version"
    export LATEXY_VERSION
    
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
    
    log "SUCCESS" "Images built with exact revision: $LATEXY_VERSION"
}

# Start only stateful dependencies before migrations. Existing app processes may
# still serve the previous revision; no new revision process starts until the
# exact backend image has completed Alembic successfully.
start_stateful_services() {
    log "INFO" "Starting stateful dependencies for migration..."
    if docker-compose -f docker-compose.prod.yml up -d --wait \
        postgres redis minio tempo; then
        # minio-init is a one-shot job; run it after MinIO is healthy rather
        # than asking --wait to treat an exited init container as a service.
        if ! docker-compose -f docker-compose.prod.yml run --rm --no-deps minio-init; then
            log "ERROR" "Object-storage bucket initialization failed"
            return 1
        fi
        log "SUCCESS" "Stateful dependencies are ready"
    else
        log "ERROR" "Stateful dependencies failed to become ready"
        return 1
    fi
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
    if docker-compose -f docker-compose.prod.yml up -d --no-build --remove-orphans; then
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
        
        # Check backend health. The backend port is not published on the host —
        # only nginx is — so probe it from inside the container.
        if docker-compose -f docker-compose.prod.yml exec -T backend \
            curl -f -s "http://localhost:${BACKEND_PORT}/health" > /dev/null; then
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
    
    # Check the proxy itself (port 80 serves /health, everything else is a 301)
    if curl -f -s "http://localhost/health" > /dev/null; then
        log "SUCCESS" "Nginx proxy is healthy"
    else
        log "WARNING" "Nginx proxy health check failed"
    fi
    
    return 0
}

# Function to run database migrations
run_migrations() {
    log "INFO" "Running database migrations..."
    
    if docker-compose -f docker-compose.prod.yml run --rm --no-deps backend alembic upgrade head; then
        log "SUCCESS" "Database migrations completed"
    else
        log "ERROR" "Database migrations failed"
        return 1
    fi
}

# Function to rollback deployment
rollback_deployment() {
    local version="$1"

    validate_image_version "$version"
    
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
    
    # Point every Compose service, including the migration container, at the
    # requested exact rollback revision. Do not retag through :latest.
    LATEXY_VERSION="$version"
    export LATEXY_VERSION

    # Migrate before starting application processes, preserving the rollback
    # backup/recovery boundary used by the previous implementation.
    if start_stateful_services && run_migrations && deploy_services; then
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
    for image in "${IMAGE_PREFIX}/latexy-frontend" "${IMAGE_PREFIX}/latexy-backend"; do
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

    case "$DEPLOY_ENV" in
        production)
            ;;
        staging)
            log "ERROR" "Staging topology is not configured; refusing to use production Compose"
            return 1
            ;;
        *)
            log "ERROR" "Unsupported deployment environment: $DEPLOY_ENV"
            return 1
            ;;
    esac
    
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
        if ! check_prerequisites; then
            send_notification "error" "$rollback_version" "Prerequisites check failed"
            exit 1
        fi
        load_environment
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

    if [[ "$skip_build" == "true" ]]; then
        if [[ -z "${LATEXY_VERSION:-}" ]]; then
            log "ERROR" "--skip-build requires LATEXY_VERSION for the exact prebuilt image"
            exit 1
        fi
        if [[ -n "${LATEXY_VERSION:-}" ]]; then
            if ! validate_image_version "$LATEXY_VERSION"; then
                exit 1
            fi
            export LATEXY_VERSION
        fi
    else
        # A normal build and its migration/deploy must share the revision that
        # was just built, regardless of a stale value in the env file.
        LATEXY_VERSION="$version"
        if ! validate_image_version "$LATEXY_VERSION"; then
            exit 1
        fi
        export LATEXY_VERSION
    fi
    
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
    
    # Build exact application images, start only stateful dependencies, and run
    # migrations from that same backend image before any new revision process starts.
    if [[ "$dry_run" != "true" && "$skip_build" != "true" ]]; then
        if ! build_images; then
            send_notification "error" "$version" "Image build failed"
            exit 1
        fi
    fi

    if [[ "$dry_run" != "true" ]]; then
        if ! start_stateful_services; then
            send_notification "error" "$version" "Stateful dependency startup failed"
            exit 1
        fi
        if ! run_migrations; then
            send_notification "error" "$version" "Database migrations failed"
            exit 1
        fi
    fi

    # Deploy services
    if ! deploy_services "$dry_run"; then
        send_notification "error" "$version" "Service deployment failed"
        exit 1
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
