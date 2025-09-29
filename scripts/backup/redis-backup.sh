#!/bin/bash

# Redis Backup Script for Latexy Production
# This script creates automated backups of Redis data

set -euo pipefail

# Configuration
BACKUP_DIR="/opt/backups/redis"
RETENTION_DAYS=7
TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
BACKUP_FILE="redis_backup_${TIMESTAMP}.rdb"
S3_BUCKET="${BACKUP_S3_BUCKET:-latexy-backups}"

# Load environment variables
if [ -f "/opt/latexy/.env.prod" ]; then
    source /opt/latexy/.env.prod
fi

# Redis connection details
REDIS_HOST="${REDIS_HOST:-localhost}"
REDIS_PORT="${REDIS_PORT:-6379}"
REDIS_PASSWORD="${REDIS_PASSWORD:-}"

# Create backup directory if it doesn't exist
mkdir -p "$BACKUP_DIR"

# Function to log messages
log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" | tee -a "$BACKUP_DIR/backup.log"
}

# Function to send notification
send_notification() {
    local status=$1
    local message=$2
    
    # Send to monitoring system
    curl -X POST "${MONITORING_WEBHOOK_URL}" \
        -H "Content-Type: application/json" \
        -d "{\"status\": \"$status\", \"message\": \"$message\", \"service\": \"redis-backup\"}" \
        2>/dev/null || true
}

# Function to cleanup old backups
cleanup_old_backups() {
    log "Cleaning up Redis backups older than $RETENTION_DAYS days"
    find "$BACKUP_DIR" -name "redis_backup_*.rdb*" -mtime +$RETENTION_DAYS -delete
    
    # Cleanup S3 backups if AWS CLI is available
    if command -v aws &> /dev/null; then
        aws s3 ls "s3://$S3_BUCKET/redis/" | while read -r line; do
            backup_date=$(echo "$line" | awk '{print $1}')
            backup_file=$(echo "$line" | awk '{print $4}')
            
            if [[ -n "$backup_date" && -n "$backup_file" ]]; then
                backup_timestamp=$(date -d "$backup_date" +%s)
                cutoff_timestamp=$(date -d "$RETENTION_DAYS days ago" +%s)
                
                if [[ $backup_timestamp -lt $cutoff_timestamp ]]; then
                    log "Deleting old S3 Redis backup: $backup_file"
                    aws s3 rm "s3://$S3_BUCKET/redis/$backup_file"
                fi
            fi
        done
    fi
}

# Function to create Redis backup
create_backup() {
    log "Starting Redis backup: $BACKUP_FILE"
    
    # Build redis-cli command
    REDIS_CMD="redis-cli -h $REDIS_HOST -p $REDIS_PORT"
    if [[ -n "$REDIS_PASSWORD" ]]; then
        REDIS_CMD="$REDIS_CMD -a $REDIS_PASSWORD"
    fi
    
    # Trigger BGSAVE
    if $REDIS_CMD BGSAVE; then
        log "Redis BGSAVE initiated"
        
        # Wait for BGSAVE to complete
        while true; do
            LASTSAVE_TIME=$($REDIS_CMD LASTSAVE)
            sleep 2
            NEW_LASTSAVE_TIME=$($REDIS_CMD LASTSAVE)
            
            if [[ "$NEW_LASTSAVE_TIME" != "$LASTSAVE_TIME" ]]; then
                log "Redis BGSAVE completed"
                break
            fi
            
            # Check if BGSAVE is still in progress
            if $REDIS_CMD INFO persistence | grep -q "rdb_bgsave_in_progress:1"; then
                log "BGSAVE still in progress..."
                sleep 5
            else
                break
            fi
        done
        
        # Copy the RDB file
        REDIS_DATA_DIR="/var/lib/redis"
        if [[ -f "$REDIS_DATA_DIR/dump.rdb" ]]; then
            cp "$REDIS_DATA_DIR/dump.rdb" "$BACKUP_DIR/$BACKUP_FILE"
            log "Redis backup file copied successfully"
            
            # Compress the backup
            gzip "$BACKUP_DIR/$BACKUP_FILE"
            COMPRESSED_FILE="${BACKUP_FILE}.gz"
            
            # Calculate file size
            BACKUP_SIZE=$(du -h "$BACKUP_DIR/$COMPRESSED_FILE" | cut -f1)
            log "Redis backup compressed to $BACKUP_SIZE"
            
            # Upload to S3 if AWS CLI is available
            if command -v aws &> /dev/null && [[ -n "$S3_BUCKET" ]]; then
                log "Uploading Redis backup to S3: s3://$S3_BUCKET/redis/$COMPRESSED_FILE"
                if aws s3 cp "$BACKUP_DIR/$COMPRESSED_FILE" "s3://$S3_BUCKET/redis/$COMPRESSED_FILE"; then
                    log "Redis backup uploaded to S3 successfully"
                    send_notification "success" "Redis backup completed successfully. Size: $BACKUP_SIZE"
                else
                    log "ERROR: Failed to upload Redis backup to S3"
                    send_notification "error" "Redis backup created but S3 upload failed"
                fi
            else
                log "S3 upload skipped (AWS CLI not available or S3_BUCKET not set)"
                send_notification "success" "Redis backup completed successfully (local only). Size: $BACKUP_SIZE"
            fi
            
            return 0
        else
            log "ERROR: Redis dump.rdb file not found"
            send_notification "error" "Redis backup failed - dump.rdb not found"
            return 1
        fi
    else
        log "ERROR: Redis BGSAVE failed"
        send_notification "error" "Redis BGSAVE command failed"
        return 1
    fi
}

# Function to verify backup integrity
verify_backup() {
    local backup_file="$1"
    log "Verifying Redis backup integrity: $backup_file"
    
    # Test if the compressed file is valid
    if gzip -t "$backup_file"; then
        log "Redis backup file integrity verified"
        return 0
    else
        log "ERROR: Redis backup file is corrupted"
        send_notification "error" "Redis backup file integrity check failed"
        return 1
    fi
}

# Function to get Redis info
get_redis_info() {
    log "Getting Redis information"
    
    REDIS_CMD="redis-cli -h $REDIS_HOST -p $REDIS_PORT"
    if [[ -n "$REDIS_PASSWORD" ]]; then
        REDIS_CMD="$REDIS_CMD -a $REDIS_PASSWORD"
    fi
    
    # Get Redis info
    REDIS_VERSION=$($REDIS_CMD INFO server | grep "redis_version" | cut -d: -f2 | tr -d '\r')
    USED_MEMORY=$($REDIS_CMD INFO memory | grep "used_memory_human" | cut -d: -f2 | tr -d '\r')
    CONNECTED_CLIENTS=$($REDIS_CMD INFO clients | grep "connected_clients" | cut -d: -f2 | tr -d '\r')
    
    log "Redis Version: $REDIS_VERSION"
    log "Used Memory: $USED_MEMORY"
    log "Connected Clients: $CONNECTED_CLIENTS"
}

# Main execution
main() {
    log "=== Starting Latexy Redis Backup ==="
    
    # Check if required tools are available
    if ! command -v redis-cli &> /dev/null; then
        log "ERROR: redis-cli is not available"
        send_notification "error" "redis-cli tool not found"
        exit 1
    fi
    
    # Test Redis connection
    REDIS_CMD="redis-cli -h $REDIS_HOST -p $REDIS_PORT"
    if [[ -n "$REDIS_PASSWORD" ]]; then
        REDIS_CMD="$REDIS_CMD -a $REDIS_PASSWORD"
    fi
    
    if ! $REDIS_CMD ping > /dev/null 2>&1; then
        log "ERROR: Cannot connect to Redis server"
        send_notification "error" "Redis connection failed"
        exit 1
    fi
    
    # Get Redis info
    get_redis_info
    
    # Create backup
    if create_backup; then
        # Verify backup
        if verify_backup "$BACKUP_DIR/${BACKUP_FILE}.gz"; then
            # Cleanup old backups
            cleanup_old_backups
            log "=== Redis backup process completed successfully ==="
        else
            log "=== Redis backup process completed with integrity issues ==="
            exit 1
        fi
    else
        log "=== Redis backup process failed ==="
        exit 1
    fi
}

# Run the main function
main "$@"
