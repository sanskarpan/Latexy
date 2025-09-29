#!/bin/bash

# Log Aggregator Script for Latexy Production
# This script collects and processes logs from all services

set -euo pipefail

# Configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
LOG_DIR="/var/log/latexy"
ARCHIVE_DIR="/var/log/latexy/archive"
RETENTION_DAYS=30
MAX_LOG_SIZE="100M"

# Load environment variables
if [ -f "$PROJECT_ROOT/.env.production" ]; then
    source "$PROJECT_ROOT/.env.production"
fi

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

# Function to create log directories
setup_log_directories() {
    log "INFO" "Setting up log directories"
    
    mkdir -p "$LOG_DIR"/{backend,frontend,nginx,postgres,redis,celery,system}
    mkdir -p "$ARCHIVE_DIR"
    
    # Set appropriate permissions
    chmod 755 "$LOG_DIR"
    chmod 755 "$ARCHIVE_DIR"
    
    log "SUCCESS" "Log directories created"
}

# Function to collect Docker container logs
collect_docker_logs() {
    log "INFO" "Collecting Docker container logs"
    
    if ! command -v docker &> /dev/null; then
        log "WARNING" "Docker not available, skipping container logs"
        return 0
    fi
    
    local timestamp
    timestamp=$(date +"%Y%m%d_%H%M%S")
    
    # Get list of Latexy containers
    local containers
    containers=$(docker ps --format "{{.Names}}" | grep -E "(latexy|frontend|backend|postgres|redis|celery|nginx)" || true)
    
    if [[ -z "$containers" ]]; then
        log "WARNING" "No Latexy containers found"
        return 0
    fi
    
    for container in $containers; do
        log "INFO" "Collecting logs from container: $container"
        
        local service_name
        service_name=$(echo "$container" | sed 's/.*_\([^_]*\)_[0-9]*/\1/' | sed 's/latexy-//')
        
        local log_file="$LOG_DIR/$service_name/${container}_${timestamp}.log"
        
        # Collect recent logs (last 1000 lines)
        if docker logs --tail 1000 "$container" > "$log_file" 2>&1; then
            log "SUCCESS" "Collected logs from $container"
            
            # Compress if file is large
            if [[ $(stat -f%z "$log_file" 2>/dev/null || stat -c%s "$log_file" 2>/dev/null) -gt 1048576 ]]; then
                gzip "$log_file"
                log "INFO" "Compressed large log file: ${log_file}.gz"
            fi
        else
            log "ERROR" "Failed to collect logs from $container"
        fi
    done
}

# Function to collect system logs
collect_system_logs() {
    log "INFO" "Collecting system logs"
    
    local timestamp
    timestamp=$(date +"%Y%m%d_%H%M%S")
    
    # Collect system metrics
    {
        echo "=== System Information ==="
        echo "Timestamp: $(date)"
        echo "Uptime: $(uptime)"
        echo ""
        
        echo "=== Memory Usage ==="
        free -h
        echo ""
        
        echo "=== Disk Usage ==="
        df -h
        echo ""
        
        echo "=== CPU Usage ==="
        top -bn1 | head -20
        echo ""
        
        echo "=== Network Connections ==="
        netstat -tuln | head -20
        echo ""
        
        echo "=== Docker Stats ==="
        if command -v docker &> /dev/null; then
            docker stats --no-stream --format "table {{.Container}}\t{{.CPUPerc}}\t{{.MemUsage}}\t{{.NetIO}}\t{{.BlockIO}}"
        fi
        
    } > "$LOG_DIR/system/system_metrics_${timestamp}.log"
    
    # Collect kernel logs (if available)
    if [[ -f /var/log/kern.log ]]; then
        tail -1000 /var/log/kern.log > "$LOG_DIR/system/kernel_${timestamp}.log" 2>/dev/null || true
    fi
    
    # Collect auth logs (if available)
    if [[ -f /var/log/auth.log ]]; then
        tail -1000 /var/log/auth.log > "$LOG_DIR/system/auth_${timestamp}.log" 2>/dev/null || true
    fi
    
    log "SUCCESS" "System logs collected"
}

# Function to collect application logs
collect_application_logs() {
    log "INFO" "Collecting application logs"
    
    local timestamp
    timestamp=$(date +"%Y%m%d_%H%M%S")
    
    # Collect backend logs from mounted volume (if available)
    if [[ -d "/opt/latexy/backend/logs" ]]; then
        cp -r /opt/latexy/backend/logs/* "$LOG_DIR/backend/" 2>/dev/null || true
    fi
    
    # Collect Nginx logs (if available)
    if [[ -d "/var/log/nginx" ]]; then
        cp /var/log/nginx/access.log "$LOG_DIR/nginx/access_${timestamp}.log" 2>/dev/null || true
        cp /var/log/nginx/error.log "$LOG_DIR/nginx/error_${timestamp}.log" 2>/dev/null || true
    fi
    
    # Collect PostgreSQL logs (if available)
    if [[ -d "/var/log/postgresql" ]]; then
        find /var/log/postgresql -name "*.log" -exec cp {} "$LOG_DIR/postgres/" \; 2>/dev/null || true
    fi
    
    log "SUCCESS" "Application logs collected"
}

# Function to analyze logs for errors
analyze_logs() {
    log "INFO" "Analyzing logs for errors and warnings"
    
    local timestamp
    timestamp=$(date +"%Y%m%d_%H%M%S")
    local analysis_file="$LOG_DIR/analysis_${timestamp}.log"
    
    {
        echo "=== Log Analysis Report ==="
        echo "Generated: $(date)"
        echo ""
        
        # Find recent errors in all logs
        echo "=== Recent Errors (last 24 hours) ==="
        find "$LOG_DIR" -name "*.log" -mtime -1 -exec grep -l -i "error\|exception\|failed\|critical" {} \; | while read -r logfile; do
            echo "File: $logfile"
            grep -i "error\|exception\|failed\|critical" "$logfile" | tail -10
            echo ""
        done
        
        echo "=== Recent Warnings (last 24 hours) ==="
        find "$LOG_DIR" -name "*.log" -mtime -1 -exec grep -l -i "warning\|warn" {} \; | while read -r logfile; do
            echo "File: $logfile"
            grep -i "warning\|warn" "$logfile" | tail -5
            echo ""
        done
        
        # Analyze HTTP status codes (if nginx logs available)
        if ls "$LOG_DIR"/nginx/access_*.log 1> /dev/null 2>&1; then
            echo "=== HTTP Status Code Summary ==="
            cat "$LOG_DIR"/nginx/access_*.log | awk '{print $9}' | sort | uniq -c | sort -nr
            echo ""
        fi
        
        # Database connection errors
        echo "=== Database Connection Issues ==="
        find "$LOG_DIR" -name "*.log" -exec grep -l -i "connection.*refused\|connection.*timeout\|database.*error" {} \; | while read -r logfile; do
            echo "File: $logfile"
            grep -i "connection.*refused\|connection.*timeout\|database.*error" "$logfile" | tail -5
            echo ""
        done
        
    } > "$analysis_file"
    
    log "SUCCESS" "Log analysis completed: $analysis_file"
    
    # Send alert if critical errors found
    local critical_errors
    critical_errors=$(grep -c -i "critical\|fatal" "$analysis_file" || echo "0")
    
    if [[ "$critical_errors" -gt 0 ]]; then
        send_alert "log-analysis" "critical" "Found $critical_errors critical errors in logs"
    fi
}

# Function to rotate logs
rotate_logs() {
    log "INFO" "Rotating logs"
    
    local timestamp
    timestamp=$(date +"%Y%m%d_%H%M%S")
    
    # Find large log files
    find "$LOG_DIR" -name "*.log" -size +"$MAX_LOG_SIZE" | while read -r logfile; do
        log "INFO" "Rotating large log file: $logfile"
        
        # Move to archive
        local basename
        basename=$(basename "$logfile")
        local dirname
        dirname=$(dirname "$logfile")
        local service
        service=$(basename "$dirname")
        
        mkdir -p "$ARCHIVE_DIR/$service"
        
        # Compress and move
        gzip -c "$logfile" > "$ARCHIVE_DIR/$service/${basename%.log}_${timestamp}.log.gz"
        
        # Truncate original file
        > "$logfile"
        
        log "SUCCESS" "Rotated: $logfile"
    done
    
    # Archive old logs
    find "$LOG_DIR" -name "*.log" -mtime +7 | while read -r logfile; do
        local basename
        basename=$(basename "$logfile")
        local dirname
        dirname=$(dirname "$logfile")
        local service
        service=$(basename "$dirname")
        
        mkdir -p "$ARCHIVE_DIR/$service"
        
        # Move to archive
        mv "$logfile" "$ARCHIVE_DIR/$service/"
        
        log "INFO" "Archived old log: $logfile"
    done
}

# Function to cleanup old archives
cleanup_old_logs() {
    log "INFO" "Cleaning up old log archives"
    
    # Remove archives older than retention period
    find "$ARCHIVE_DIR" -name "*.log*" -mtime +"$RETENTION_DAYS" -delete
    
    # Remove empty directories
    find "$ARCHIVE_DIR" -type d -empty -delete
    
    log "SUCCESS" "Old log cleanup completed"
}

# Function to send logs to external system
send_logs_to_external() {
    if [[ -z "${LOG_AGGREGATION_ENDPOINT:-}" ]]; then
        log "INFO" "No external log aggregation endpoint configured"
        return 0
    fi
    
    log "INFO" "Sending logs to external aggregation system"
    
    # Find recent log files
    find "$LOG_DIR" -name "*.log" -mtime -1 | while read -r logfile; do
        local service
        service=$(basename "$(dirname "$logfile")")
        
        # Send to external system (example with curl)
        if curl -X POST "$LOG_AGGREGATION_ENDPOINT" \
            -H "Content-Type: application/json" \
            -H "X-Service: $service" \
            -H "X-Timestamp: $(date -u +'%Y-%m-%dT%H:%M:%SZ')" \
            --data-binary "@$logfile" \
            --max-time 30 \
            2>/dev/null; then
            log "SUCCESS" "Sent $logfile to external system"
        else
            log "WARNING" "Failed to send $logfile to external system"
        fi
    done
}

# Function to send alert
send_alert() {
    local service="$1"
    local level="$2"
    local message="$3"
    
    if [[ -n "${MONITORING_WEBHOOK_URL:-}" ]]; then
        curl -X POST "$MONITORING_WEBHOOK_URL" \
            -H "Content-Type: application/json" \
            -d "{
                \"service\": \"$service\",
                \"level\": \"$level\",
                \"message\": \"$message\",
                \"timestamp\": \"$(date -u +'%Y-%m-%dT%H:%M:%SZ')\"
            }" \
            --max-time 10 \
            2>/dev/null || true
    fi
}

# Function to generate log summary
generate_summary() {
    log "INFO" "Generating log summary"
    
    local timestamp
    timestamp=$(date +"%Y%m%d_%H%M%S")
    local summary_file="$LOG_DIR/summary_${timestamp}.json"
    
    {
        echo "{"
        echo "  \"timestamp\": \"$(date -u +'%Y-%m-%dT%H:%M:%SZ')\","
        echo "  \"log_directories\": {"
        
        for service_dir in "$LOG_DIR"/*; do
            if [[ -d "$service_dir" ]]; then
                local service
                service=$(basename "$service_dir")
                local file_count
                file_count=$(find "$service_dir" -name "*.log" | wc -l)
                local total_size
                total_size=$(du -sh "$service_dir" 2>/dev/null | cut -f1 || echo "0")
                
                echo "    \"$service\": {"
                echo "      \"file_count\": $file_count,"
                echo "      \"total_size\": \"$total_size\""
                echo "    },"
            fi
        done | sed '$ s/,$//'
        
        echo "  },"
        echo "  \"archive_size\": \"$(du -sh "$ARCHIVE_DIR" 2>/dev/null | cut -f1 || echo "0")\","
        echo "  \"retention_days\": $RETENTION_DAYS"
        echo "}"
        
    } > "$summary_file"
    
    log "SUCCESS" "Log summary generated: $summary_file"
}

# Function to show usage
usage() {
    echo "Usage: $0 [OPTIONS]"
    echo ""
    echo "Options:"
    echo "  --collect-only       Only collect logs, skip analysis"
    echo "  --analyze-only       Only analyze existing logs"
    echo "  --rotate-only        Only rotate logs"
    echo "  --cleanup-only       Only cleanup old logs"
    echo "  --service SERVICE    Process logs for specific service only"
    echo "  --send-external      Send logs to external aggregation system"
    echo "  -h, --help           Show this help message"
    echo ""
    echo "Services: backend, frontend, nginx, postgres, redis, celery, system"
}

# Main execution
main() {
    local collect_only=false
    local analyze_only=false
    local rotate_only=false
    local cleanup_only=false
    local specific_service=""
    local send_external=false
    
    # Parse command line arguments
    while [[ $# -gt 0 ]]; do
        case $1 in
            --collect-only)
                collect_only=true
                shift
                ;;
            --analyze-only)
                analyze_only=true
                shift
                ;;
            --rotate-only)
                rotate_only=true
                shift
                ;;
            --cleanup-only)
                cleanup_only=true
                shift
                ;;
            --service)
                specific_service="$2"
                shift 2
                ;;
            --send-external)
                send_external=true
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
    
    log "INFO" "=== Starting Latexy Log Aggregation ==="
    
    # Setup directories
    setup_log_directories
    
    # Execute based on options
    if [[ "$collect_only" == "true" ]]; then
        collect_docker_logs
        collect_system_logs
        collect_application_logs
    elif [[ "$analyze_only" == "true" ]]; then
        analyze_logs
    elif [[ "$rotate_only" == "true" ]]; then
        rotate_logs
    elif [[ "$cleanup_only" == "true" ]]; then
        cleanup_old_logs
    else
        # Full log aggregation process
        collect_docker_logs
        collect_system_logs
        collect_application_logs
        analyze_logs
        rotate_logs
        cleanup_old_logs
        generate_summary
        
        if [[ "$send_external" == "true" ]]; then
            send_logs_to_external
        fi
    fi
    
    log "SUCCESS" "=== Log aggregation completed ==="
}

# Run the main function
main "$@"
