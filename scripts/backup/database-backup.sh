#!/bin/bash

# Database Backup Script for Latexy Production
# This script creates automated backups of the PostgreSQL database

set -euo pipefail

# Configuration
BACKUP_DIR="/opt/backups/database"
RETENTION_DAYS=30
TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
BACKUP_FILE="latexy_backup_${TIMESTAMP}.sql"
S3_BUCKET="${BACKUP_S3_BUCKET:-latexy-backups}"

# Load environment variables
if [ -f "/opt/latexy/.env.prod" ]; then
    source /opt/latexy/.env.prod
fi

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
    
    # Send to monitoring system (replace with your notification system)
    curl -X POST "${MONITORING_WEBHOOK_URL}" \
        -H "Content-Type: application/json" \
        -d "{\"status\": \"$status\", \"message\": \"$message\", \"service\": \"database-backup\"}" \
        2>/dev/null || true
}

# Function to cleanup old backups
cleanup_old_backups() {
    log "Cleaning up backups older than $RETENTION_DAYS days"
    find "$BACKUP_DIR" -name "latexy_backup_*.sql*" -mtime +$RETENTION_DAYS -delete
    
    # Cleanup S3 backups if AWS CLI is available
    if command -v aws &> /dev/null; then
        aws s3 ls "s3://$S3_BUCKET/" | while read -r line; do
            backup_date=$(echo "$line" | awk '{print $1}')
            backup_file=$(echo "$line" | awk '{print $4}')
            
            if [[ -n "$backup_date" && -n "$backup_file" ]]; then
                backup_timestamp=$(date -d "$backup_date" +%s)
                cutoff_timestamp=$(date -d "$RETENTION_DAYS days ago" +%s)
                
                if [[ $backup_timestamp -lt $cutoff_timestamp ]]; then
                    log "Deleting old S3 backup: $backup_file"
                    aws s3 rm "s3://$S3_BUCKET/$backup_file"
                fi
            fi
        done
    fi
}

# Function to create database backup
create_backup() {
    log "Starting database backup: $BACKUP_FILE"
    
    # Create the backup
    if pg_dump "$DATABASE_URL" > "$BACKUP_DIR/$BACKUP_FILE"; then
        log "Database backup created successfully"
        
        # Compress the backup
        gzip "$BACKUP_DIR/$BACKUP_FILE"
        COMPRESSED_FILE="${BACKUP_FILE}.gz"
        
        # Calculate file size
        BACKUP_SIZE=$(du -h "$BACKUP_DIR/$COMPRESSED_FILE" | cut -f1)
        log "Backup compressed to $BACKUP_SIZE"
        
        # Upload to S3 if AWS CLI is available
        if command -v aws &> /dev/null && [[ -n "$S3_BUCKET" ]]; then
            log "Uploading backup to S3: s3://$S3_BUCKET/$COMPRESSED_FILE"
            if aws s3 cp "$BACKUP_DIR/$COMPRESSED_FILE" "s3://$S3_BUCKET/$COMPRESSED_FILE"; then
                log "Backup uploaded to S3 successfully"
                send_notification "success" "Database backup completed successfully. Size: $BACKUP_SIZE"
            else
                log "ERROR: Failed to upload backup to S3"
                send_notification "error" "Database backup created but S3 upload failed"
            fi
        else
            log "S3 upload skipped (AWS CLI not available or S3_BUCKET not set)"
            send_notification "success" "Database backup completed successfully (local only). Size: $BACKUP_SIZE"
        fi
        
        return 0
    else
        log "ERROR: Database backup failed"
        send_notification "error" "Database backup failed"
        return 1
    fi
}

# Function to verify backup integrity
verify_backup() {
    local backup_file="$1"
    log "Verifying backup integrity: $backup_file"
    
    # Test if the compressed file is valid
    if gzip -t "$backup_file"; then
        log "Backup file integrity verified"
        return 0
    else
        log "ERROR: Backup file is corrupted"
        send_notification "error" "Backup file integrity check failed"
        return 1
    fi
}

# Main execution
main() {
    log "=== Starting Latexy Database Backup ==="
    
    # Check if required tools are available
    if ! command -v pg_dump &> /dev/null; then
        log "ERROR: pg_dump is not available"
        send_notification "error" "pg_dump tool not found"
        exit 1
    fi
    
    if [[ -z "${DATABASE_URL:-}" ]]; then
        log "ERROR: DATABASE_URL environment variable is not set"
        send_notification "error" "DATABASE_URL not configured"
        exit 1
    fi
    
    # Create backup
    if create_backup; then
        # Verify backup
        if verify_backup "$BACKUP_DIR/${BACKUP_FILE}.gz"; then
            # Cleanup old backups
            cleanup_old_backups
            log "=== Backup process completed successfully ==="
        else
            log "=== Backup process completed with integrity issues ==="
            exit 1
        fi
    else
        log "=== Backup process failed ==="
        exit 1
    fi
}

# Run the main function
main "$@"
