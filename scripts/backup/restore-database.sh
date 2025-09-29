#!/bin/bash

# Database Restore Script for Latexy Production
# This script restores PostgreSQL database from backup

set -euo pipefail

# Configuration
BACKUP_DIR="/opt/backups/database"
S3_BUCKET="${BACKUP_S3_BUCKET:-latexy-backups}"

# Load environment variables
if [ -f "/opt/latexy/.env.prod" ]; then
    source /opt/latexy/.env.prod
fi

# Function to log messages
log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1"
}

# Function to show usage
usage() {
    echo "Usage: $0 [OPTIONS]"
    echo ""
    echo "Options:"
    echo "  -f, --file BACKUP_FILE    Restore from specific backup file"
    echo "  -s, --s3 S3_KEY          Restore from S3 backup"
    echo "  -l, --list               List available backups"
    echo "  --latest                 Restore from latest backup"
    echo "  --dry-run                Show what would be restored without executing"
    echo "  -h, --help               Show this help message"
    echo ""
    echo "Examples:"
    echo "  $0 --latest                                    # Restore from latest local backup"
    echo "  $0 -f latexy_backup_20241201_120000.sql.gz   # Restore from specific file"
    echo "  $0 -s latexy_backup_20241201_120000.sql.gz   # Restore from S3"
    echo "  $0 --list                                     # List available backups"
}

# Function to list available backups
list_backups() {
    log "=== Available Local Backups ==="
    if ls "$BACKUP_DIR"/latexy_backup_*.sql.gz 2>/dev/null; then
        for backup in "$BACKUP_DIR"/latexy_backup_*.sql.gz; do
            if [[ -f "$backup" ]]; then
                size=$(du -h "$backup" | cut -f1)
                date=$(stat -c %y "$backup" | cut -d' ' -f1,2)
                echo "  $(basename "$backup") - $size - $date"
            fi
        done
    else
        echo "  No local backups found"
    fi
    
    if command -v aws &> /dev/null && [[ -n "$S3_BUCKET" ]]; then
        log "=== Available S3 Backups ==="
        if aws s3 ls "s3://$S3_BUCKET/" --recursive | grep "latexy_backup_.*\.sql\.gz"; then
            echo "  (Use -s option to restore from S3)"
        else
            echo "  No S3 backups found"
        fi
    fi
}

# Function to get latest backup
get_latest_backup() {
    local latest_backup
    latest_backup=$(ls -t "$BACKUP_DIR"/latexy_backup_*.sql.gz 2>/dev/null | head -1)
    
    if [[ -n "$latest_backup" && -f "$latest_backup" ]]; then
        echo "$latest_backup"
    else
        return 1
    fi
}

# Function to download from S3
download_from_s3() {
    local s3_key="$1"
    local local_file="$BACKUP_DIR/temp_$(basename "$s3_key")"
    
    log "Downloading backup from S3: s3://$S3_BUCKET/$s3_key"
    
    if aws s3 cp "s3://$S3_BUCKET/$s3_key" "$local_file"; then
        echo "$local_file"
    else
        log "ERROR: Failed to download backup from S3"
        return 1
    fi
}

# Function to verify backup file
verify_backup_file() {
    local backup_file="$1"
    
    log "Verifying backup file: $(basename "$backup_file")"
    
    # Check if file exists
    if [[ ! -f "$backup_file" ]]; then
        log "ERROR: Backup file does not exist: $backup_file"
        return 1
    fi
    
    # Check if file is compressed and valid
    if [[ "$backup_file" == *.gz ]]; then
        if ! gzip -t "$backup_file"; then
            log "ERROR: Backup file is corrupted: $backup_file"
            return 1
        fi
    fi
    
    # Check file size
    local file_size
    file_size=$(du -h "$backup_file" | cut -f1)
    log "Backup file size: $file_size"
    
    return 0
}

# Function to create database backup before restore
create_pre_restore_backup() {
    local timestamp
    timestamp=$(date +"%Y%m%d_%H%M%S")
    local pre_restore_backup="$BACKUP_DIR/pre_restore_backup_${timestamp}.sql"
    
    log "Creating pre-restore backup: $(basename "$pre_restore_backup")"
    
    if pg_dump "$DATABASE_URL" > "$pre_restore_backup"; then
        gzip "$pre_restore_backup"
        log "Pre-restore backup created: ${pre_restore_backup}.gz"
        return 0
    else
        log "ERROR: Failed to create pre-restore backup"
        return 1
    fi
}

# Function to restore database
restore_database() {
    local backup_file="$1"
    local dry_run="${2:-false}"
    
    log "=== Starting Database Restore ==="
    log "Backup file: $(basename "$backup_file")"
    
    if [[ "$dry_run" == "true" ]]; then
        log "DRY RUN: Would restore from $backup_file"
        log "DRY RUN: Would drop existing database and recreate"
        log "DRY RUN: Would restore data from backup"
        return 0
    fi
    
    # Verify backup file
    if ! verify_backup_file "$backup_file"; then
        return 1
    fi
    
    # Create pre-restore backup
    if ! create_pre_restore_backup; then
        log "WARNING: Could not create pre-restore backup, continuing anyway"
    fi
    
    # Parse database URL to get connection details
    local db_name
    db_name=$(echo "$DATABASE_URL" | sed -n 's/.*\/\([^?]*\).*/\1/p')
    local db_url_without_name
    db_url_without_name=$(echo "$DATABASE_URL" | sed 's/\/[^\/]*$/\/postgres/')
    
    log "Database name: $db_name"
    
    # Terminate existing connections to the database
    log "Terminating existing database connections"
    psql "$db_url_without_name" -c "
        SELECT pg_terminate_backend(pid) 
        FROM pg_stat_activity 
        WHERE datname = '$db_name' AND pid <> pg_backend_pid();
    " || true
    
    # Drop and recreate database
    log "Dropping existing database: $db_name"
    psql "$db_url_without_name" -c "DROP DATABASE IF EXISTS \"$db_name\";"
    
    log "Creating new database: $db_name"
    psql "$db_url_without_name" -c "CREATE DATABASE \"$db_name\";"
    
    # Restore from backup
    log "Restoring data from backup"
    if [[ "$backup_file" == *.gz ]]; then
        if gunzip -c "$backup_file" | psql "$DATABASE_URL"; then
            log "Database restored successfully"
            return 0
        else
            log "ERROR: Database restore failed"
            return 1
        fi
    else
        if psql "$DATABASE_URL" < "$backup_file"; then
            log "Database restored successfully"
            return 0
        else
            log "ERROR: Database restore failed"
            return 1
        fi
    fi
}

# Function to cleanup temporary files
cleanup() {
    if [[ -n "${temp_file:-}" && -f "$temp_file" ]]; then
        log "Cleaning up temporary file: $temp_file"
        rm -f "$temp_file"
    fi
}

# Set trap for cleanup
trap cleanup EXIT

# Main execution
main() {
    local backup_file=""
    local s3_key=""
    local list_only=false
    local use_latest=false
    local dry_run=false
    
    # Parse command line arguments
    while [[ $# -gt 0 ]]; do
        case $1 in
            -f|--file)
                backup_file="$2"
                shift 2
                ;;
            -s|--s3)
                s3_key="$2"
                shift 2
                ;;
            -l|--list)
                list_only=true
                shift
                ;;
            --latest)
                use_latest=true
                shift
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
                log "ERROR: Unknown option: $1"
                usage
                exit 1
                ;;
        esac
    done
    
    # Check if required tools are available
    if ! command -v pg_dump &> /dev/null || ! command -v psql &> /dev/null; then
        log "ERROR: PostgreSQL tools (pg_dump, psql) are not available"
        exit 1
    fi
    
    if [[ -z "${DATABASE_URL:-}" ]]; then
        log "ERROR: DATABASE_URL environment variable is not set"
        exit 1
    fi
    
    # Create backup directory if it doesn't exist
    mkdir -p "$BACKUP_DIR"
    
    # Handle list option
    if [[ "$list_only" == "true" ]]; then
        list_backups
        exit 0
    fi
    
    # Determine backup file to use
    if [[ -n "$s3_key" ]]; then
        if ! command -v aws &> /dev/null; then
            log "ERROR: AWS CLI is not available for S3 restore"
            exit 1
        fi
        temp_file=$(download_from_s3 "$s3_key")
        backup_file="$temp_file"
    elif [[ -n "$backup_file" ]]; then
        # Check if it's a relative path
        if [[ "$backup_file" != /* ]]; then
            backup_file="$BACKUP_DIR/$backup_file"
        fi
    elif [[ "$use_latest" == "true" ]]; then
        backup_file=$(get_latest_backup)
        if [[ -z "$backup_file" ]]; then
            log "ERROR: No local backups found"
            exit 1
        fi
    else
        log "ERROR: No backup source specified"
        usage
        exit 1
    fi
    
    # Confirm restore operation (unless dry run)
    if [[ "$dry_run" != "true" ]]; then
        echo ""
        echo "WARNING: This will completely replace the current database!"
        echo "Backup file: $(basename "$backup_file")"
        echo ""
        read -p "Are you sure you want to continue? (yes/no): " -r
        if [[ ! $REPLY =~ ^[Yy][Ee][Ss]$ ]]; then
            log "Restore operation cancelled"
            exit 0
        fi
    fi
    
    # Perform restore
    if restore_database "$backup_file" "$dry_run"; then
        log "=== Database restore completed successfully ==="
    else
        log "=== Database restore failed ==="
        exit 1
    fi
}

# Run the main function
main "$@"
