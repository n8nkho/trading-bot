#!/usr/bin/env python3
"""
Agent Manager - Health monitoring and intervention system
Monitors services, verifies cron jobs, and restarts broken components
"""

import os
import sys
import subprocess
import logging
from datetime import datetime, timedelta
from pathlib import Path
import json

# Color codes for terminal output
class Colors:
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    BLUE = '\033[94m'
    RESET = '\033[0m'
    BOLD = '\033[1m'

# Configuration
LOG_DIR = Path("logs")
LOG_FILE = LOG_DIR / "agent_manager.log"
CRON_LOGS_DIR = LOG_DIR
MAX_LOG_AGE_HOURS = 24

# Services to monitor
SERVICES = {
    'ollama': {
        'check_cmd': ['pgrep', '-f', 'ollama'],
        'start_cmd': ['ollama', 'serve'],
        'description': 'Ollama LLM service'
    },
    'dashboard': {
        'check_cmd': ['pgrep', '-f', 'dashboard/app.py'],
        'start_cmd': ['python3', 'dashboard/app.py'],
        'description': 'Trading dashboard'
    }
}

# Cron jobs to verify (log file patterns)
CRON_JOBS = {
    'daily_screening': {
        'log_pattern': 'screening_*.log',
        'description': 'Daily stock screening',
        'max_age_hours': 26  # Should run daily, allow some buffer
    },
    'position_monitoring': {
        'log_pattern': 'monitoring_*.log',
        'description': 'Position monitoring',
        'max_age_hours': 2  # Should run hourly during market hours
    },
    'fortress_check': {
        'log_pattern': 'fortress_*.log',
        'description': 'Fortress orchestrator',
        'max_age_hours': 26
    }
}

def setup_logging():
    """Initialize logging to file and console"""
    LOG_DIR.mkdir(exist_ok=True)
    
    # File handler
    file_handler = logging.FileHandler(LOG_FILE)
    file_handler.setLevel(logging.DEBUG)
    file_formatter = logging.Formatter(
        '%(asctime)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    file_handler.setFormatter(file_formatter)
    
    # Console handler (no colors in file)
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_formatter = logging.Formatter('%(message)s')
    console_handler.setFormatter(console_formatter)
    
    # Root logger
    logger = logging.getLogger()
    logger.setLevel(logging.DEBUG)
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
    
    return logger

def print_colored(message, color=Colors.RESET, bold=False):
    """Print colored message to console"""
    prefix = Colors.BOLD if bold else ''
    print(f"{prefix}{color}{message}{Colors.RESET}")

def is_service_running(service_name, config):
    """
    Check if a service is running
    
    Args:
        service_name: Name of the service
        config: Service configuration dict with check_cmd
        
    Returns:
        bool: True if running, False otherwise
    """
    try:
        result = subprocess.run(
            config['check_cmd'],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=5
        )
        is_running = result.returncode == 0 and result.stdout.strip()
        
        if is_running:
            logging.debug(f"Service '{service_name}' is running")
        else:
            logging.warning(f"Service '{service_name}' is NOT running")
            
        return is_running
        
    except subprocess.TimeoutExpired:
        logging.error(f"Timeout checking service '{service_name}'")
        return False
    except Exception as e:
        logging.error(f"Error checking service '{service_name}': {e}")
        return False

def restart_service(service_name, config):
    """
    Attempt to restart a service
    
    Args:
        service_name: Name of the service
        config: Service configuration dict with start_cmd
        
    Returns:
        bool: True if restart successful, False otherwise
    """
    try:
        logging.info(f"Attempting to restart service '{service_name}'...")
        
        # Start service in background
        process = subprocess.Popen(
            config['start_cmd'],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True
        )
        
        # Give it a moment to start
        import time
        time.sleep(2)
        
        # Verify it's running
        if is_service_running(service_name, config):
            logging.info(f"Successfully restarted service '{service_name}'")
            return True
        else:
            logging.error(f"Failed to restart service '{service_name}' - not running after start attempt")
            return False
            
    except Exception as e:
        logging.error(f"Error restarting service '{service_name}': {e}")
        return False

def get_latest_log_file(pattern):
    """
    Find the most recent log file matching pattern
    
    Args:
        pattern: Glob pattern for log files
        
    Returns:
        Path object or None if no files found
    """
    try:
        log_files = list(CRON_LOGS_DIR.glob(pattern))
        if not log_files:
            return None
        
        # Return most recently modified
        latest = max(log_files, key=lambda p: p.stat().st_mtime)
        return latest
        
    except Exception as e:
        logging.error(f"Error finding log files for pattern '{pattern}': {e}")
        return None

def is_log_fresh(log_file, max_age_hours):
    """
    Check if log file is fresh (within max_age_hours)
    
    Args:
        log_file: Path to log file
        max_age_hours: Maximum age in hours
        
    Returns:
        bool: True if fresh, False if stale
    """
    try:
        if not log_file or not log_file.exists():
            return False
        
        mod_time = datetime.fromtimestamp(log_file.stat().st_mtime)
        age = datetime.now() - mod_time
        max_age = timedelta(hours=max_age_hours)
        
        is_fresh = age <= max_age
        
        if is_fresh:
            logging.debug(f"Log file '{log_file.name}' is fresh (age: {age})")
        else:
            logging.warning(f"Log file '{log_file.name}' is stale (age: {age}, max: {max_age})")
            
        return is_fresh
        
    except Exception as e:
        logging.error(f"Error checking log freshness for '{log_file}': {e}")
        return False

def verify_cron_jobs():
    """
    Verify all cron jobs by checking log freshness
    
    Returns:
        list: List of stale job names
    """
    stale_jobs = []
    
    logging.info("Verifying cron jobs...")
    
    for job_name, config in CRON_JOBS.items():
        try:
            log_file = get_latest_log_file(config['log_pattern'])
            
            if not log_file:
                logging.warning(f"Cron job '{job_name}': No log files found for pattern '{config['log_pattern']}'")
                stale_jobs.append(job_name)
                continue
            
            if not is_log_fresh(log_file, config['max_age_hours']):
                logging.warning(f"Cron job '{job_name}': Log is stale (file: {log_file.name})")
                stale_jobs.append(job_name)
            else:
                logging.debug(f"Cron job '{job_name}': OK")
                
        except Exception as e:
            logging.error(f"Error verifying cron job '{job_name}': {e}")
            stale_jobs.append(job_name)
    
    return stale_jobs

def check_all_services():
    """
    Check all services and attempt restart if not running
    
    Returns:
        dict: Status of all services
    """
    status = {}
    
    logging.info("Checking all services...")
    
    for service_name, config in SERVICES.items():
        try:
            is_running = is_service_running(service_name, config)
            
            if is_running:
                status[service_name] = {
                    'running': True,
                    'restarted': False,
                    'description': config['description']
                }
            else:
                # Attempt restart
                logging.warning(f"Service '{service_name}' is down, attempting restart...")
                restart_success = restart_service(service_name, config)
                
                status[service_name] = {
                    'running': restart_success,
                    'restarted': restart_success,
                    'restart_failed': not restart_success,
                    'description': config['description']
                }
                
        except Exception as e:
            logging.error(f"Error checking service '{service_name}': {e}")
            status[service_name] = {
                'running': False,
                'error': str(e),
                'description': config.get('description', 'Unknown')
            }
    
    return status

def run_health_intervention():
    """
    Run complete health intervention
    
    Returns:
        dict: Summary of intervention
    """
    logging.info("=" * 60)
    logging.info("Starting Agent Manager Health Intervention")
    logging.info("=" * 60)
    
    intervention_start = datetime.now()
    
    # Check services
    service_status = check_all_services()
    
    # Verify cron jobs
    stale_jobs = verify_cron_jobs()
    
    # Generate summary
    services_ok = sum(1 for s in service_status.values() if s.get('running', False))
    services_total = len(service_status)
    services_restarted = sum(1 for s in service_status.values() if s.get('restarted', False))
    services_failed = sum(1 for s in service_status.values() if s.get('restart_failed', False))
    
    cron_jobs_ok = len(CRON_JOBS) - len(stale_jobs)
    cron_jobs_total = len(CRON_JOBS)
    
    summary = {
        'timestamp': intervention_start.isoformat(),
        'services': {
            'total': services_total,
            'running': services_ok,
            'restarted': services_restarted,
            'failed': services_failed,
            'details': service_status
        },
        'cron_jobs': {
            'total': cron_jobs_total,
            'ok': cron_jobs_ok,
            'stale': len(stale_jobs),
            'stale_jobs': stale_jobs
        },
        'all_ok': services_ok == services_total and len(stale_jobs) == 0
    }
    
    # Log summary
    logging.info("=" * 60)
    logging.info("Health Intervention Summary")
    logging.info("=" * 60)
    logging.info(f"Services: {services_ok}/{services_total} running")
    if services_restarted > 0:
        logging.info(f"  - Restarted: {services_restarted}")
    if services_failed > 0:
        logging.warning(f"  - Failed to restart: {services_failed}")
    
    logging.info(f"Cron Jobs: {cron_jobs_ok}/{cron_jobs_total} fresh")
    if stale_jobs:
        logging.warning(f"  - Stale jobs: {', '.join(stale_jobs)}")
    
    logging.info("=" * 60)
    
    return summary

def print_summary(summary):
    """Print color-coded summary to console"""
    print()
    print_colored("=" * 60, Colors.BLUE, bold=True)
    print_colored("AGENT MANAGER HEALTH REPORT", Colors.BLUE, bold=True)
    print_colored("=" * 60, Colors.BLUE, bold=True)
    print()
    
    # Services
    print_colored("SERVICES:", Colors.BOLD)
    services = summary['services']
    
    for service_name, status in services['details'].items():
        desc = status.get('description', service_name)
        
        if status.get('running'):
            if status.get('restarted'):
                print_colored(f"  ✓ {desc}: RESTARTED", Colors.YELLOW)
            else:
                print_colored(f"  ✓ {desc}: OK", Colors.GREEN)
        else:
            print_colored(f"  ✗ {desc}: DOWN", Colors.RED)
    
    print()
    
    # Cron Jobs
    print_colored("CRON JOBS:", Colors.BOLD)
    cron = summary['cron_jobs']
    
    if cron['stale'] == 0:
        print_colored(f"  ✓ All {cron['total']} jobs have fresh logs", Colors.GREEN)
    else:
        print_colored(f"  ⚠ {cron['stale']}/{cron['total']} jobs have stale logs:", Colors.YELLOW)
        for job in cron['stale_jobs']:
            job_desc = CRON_JOBS.get(job, {}).get('description', job)
            print_colored(f"    - {job_desc}", Colors.YELLOW)
    
    print()
    
    # Overall status
    if summary['all_ok']:
        print_colored("OVERALL STATUS: ALL SYSTEMS OPERATIONAL", Colors.GREEN, bold=True)
    else:
        print_colored("OVERALL STATUS: ISSUES DETECTED", Colors.RED, bold=True)
    
    print_colored("=" * 60, Colors.BLUE, bold=True)
    print()

def main():
    """Main entry point"""
    try:
        # Setup logging
        setup_logging()
        
        # Run health intervention
        summary = run_health_intervention()
        
        # Print colored summary
        print_summary(summary)
        
        # Exit with appropriate code
        if summary['all_ok']:
            logging.info("Health intervention completed successfully - all systems OK")
            return 0
        else:
            logging.warning("Health intervention completed - issues found")
            return 1
            
    except KeyboardInterrupt:
        print_colored("\nInterrupted by user", Colors.YELLOW)
        logging.info("Health intervention interrupted by user")
        return 130
    except Exception as e:
        print_colored(f"\nFATAL ERROR: {e}", Colors.RED, bold=True)
        logging.error(f"Fatal error in health intervention: {e}", exc_info=True)
        return 1

if __name__ == "__main__":
    sys.exit(main())
