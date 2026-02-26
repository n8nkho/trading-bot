"""
Error Detective Agent - Error detection and diagnostic reporting (NO auto-fixing)

Purpose: Scan all logs, detect errors, create diagnostic reports, alert user
"""

import os
import re
import logging
import json
from datetime import datetime, timedelta
import glob

# Configuration
LOG_DIRECTORIES = ['logs/']
ERROR_PATTERNS = {
    'ImportError': r'(ImportError|ModuleNotFoundError):.*',
    'SyntaxError': r'(SyntaxError|IndentationError):.*',
    'ValueError': r'ValueError:.*',
    'AttributeError': r'AttributeError:.*',
    'KeyError': r'KeyError:.*',
    'TypeError': r'TypeError:.*',
    'FileNotFoundError': r'FileNotFoundError:.*',
    'APIError': r'(API.*[Ee]rror|authentication|401|403):.*',
}

# Setup logging
os.makedirs('logs', exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('logs/error_detective.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


def scan_log_file(filepath):
    """
    Read log file and search for error patterns.
    
    Args:
        filepath: Path to log file
        
    Returns:
        list: List of error dictionaries with details
    """
    errors = []
    
    try:
        with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
            lines = f.readlines()
            
        for line_num, line in enumerate(lines, 1):
            # Extract timestamp if present
            timestamp_match = re.match(r'^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})', line)
            timestamp = timestamp_match.group(1) if timestamp_match else None
            
            # Check each error pattern
            for error_type, pattern in ERROR_PATTERNS.items():
                match = re.search(pattern, line, re.IGNORECASE)
                if match:
                    errors.append({
                        'file': filepath,
                        'line_number': line_num,
                        'error_type': error_type,
                        'error_message': match.group(0),
                        'full_line': line.strip(),
                        'timestamp': timestamp
                    })
                    
    except Exception as e:
        logger.error(f"Error scanning {filepath}: {e}")
        
    return errors


def scan_all_logs():
    """
    Scan all log files in configured directories.
    
    Returns:
        dict: {log_file: [errors]}
    """
    all_errors = {}
    
    for log_dir in LOG_DIRECTORIES:
        if not os.path.exists(log_dir):
            logger.warning(f"Log directory not found: {log_dir}")
            continue
            
        # Find all .log files
        log_files = glob.glob(os.path.join(log_dir, '*.log'))
        
        logger.info(f"Scanning {len(log_files)} log files in {log_dir}")
        
        for log_file in log_files:
            errors = scan_log_file(log_file)
            if errors:
                all_errors[log_file] = errors
                
    return all_errors


def identify_broken_agents(error_dict):
    """
    Parse which agent caused each error and group by agent.
    
    Args:
        error_dict: Dictionary of {log_file: [errors]}
        
    Returns:
        dict: {agent_name: [error_types]}
    """
    broken_agents = {}
    
    for log_file, errors in error_dict.items():
        # Extract agent name from log file path
        # e.g., logs/screener_agent.log -> screener_agent
        agent_name = os.path.basename(log_file).replace('.log', '')
        
        if agent_name not in broken_agents:
            broken_agents[agent_name] = []
            
        # Collect unique error types for this agent
        error_types = [error['error_type'] for error in errors]
        broken_agents[agent_name].extend(error_types)
        
    # Remove duplicates
    for agent in broken_agents:
        broken_agents[agent] = list(set(broken_agents[agent]))
        
    return broken_agents


def categorize_severity(error_type):
    """
    Categorize error severity level.
    
    Args:
        error_type: Type of error
        
    Returns:
        str: Severity level (CRITICAL, HIGH, MEDIUM, LOW)
    """
    if error_type in ['ImportError', 'SyntaxError']:
        return 'CRITICAL'
    elif error_type in ['ValueError', 'TypeError', 'AttributeError']:
        return 'HIGH'
    elif error_type in ['APIError']:
        return 'MEDIUM'
    else:
        return 'LOW'


def create_diagnostic_report(errors):
    """
    Format all errors into a diagnostic report.
    
    Args:
        errors: Dictionary of {log_file: [errors]}
        
    Returns:
        str: Formatted report string
    """
    report_lines = []
    report_lines.append("=" * 80)
    report_lines.append("ERROR DETECTIVE DIAGNOSTIC REPORT")
    report_lines.append(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    report_lines.append("=" * 80)
    report_lines.append("")
    
    # Count total errors
    total_errors = sum(len(errs) for errs in errors.values())
    report_lines.append(f"Total Errors Found: {total_errors}")
    report_lines.append("")
    
    # Identify broken agents
    broken_agents = identify_broken_agents(errors)
    report_lines.append(f"Affected Agents: {len(broken_agents)}")
    for agent, error_types in broken_agents.items():
        report_lines.append(f"  - {agent}: {', '.join(error_types)}")
    report_lines.append("")
    
    # Group by severity
    severity_groups = {'CRITICAL': [], 'HIGH': [], 'MEDIUM': [], 'LOW': []}
    
    for log_file, error_list in errors.items():
        for error in error_list:
            severity = categorize_severity(error['error_type'])
            severity_groups[severity].append(error)
    
    # Report by severity
    for severity in ['CRITICAL', 'HIGH', 'MEDIUM', 'LOW']:
        error_list = severity_groups[severity]
        if not error_list:
            continue
            
        report_lines.append("-" * 80)
        report_lines.append(f"{severity} SEVERITY ERRORS ({len(error_list)})")
        report_lines.append("-" * 80)
        
        for error in error_list:
            report_lines.append(f"\nFile: {error['file']}")
            report_lines.append(f"Line: {error['line_number']}")
            report_lines.append(f"Type: {error['error_type']}")
            report_lines.append(f"Message: {error['error_message']}")
            if error['timestamp']:
                report_lines.append(f"Time: {error['timestamp']}")
            report_lines.append(f"Context: {error['full_line'][:200]}")
            
            # Suggest fixes (but don't apply!)
            report_lines.append("\nSuggested Fix:")
            if error['error_type'] == 'ImportError':
                report_lines.append("  - Check if module is installed")
                report_lines.append("  - Verify import path is correct")
                report_lines.append("  - Check for circular imports")
            elif error['error_type'] == 'SyntaxError':
                report_lines.append("  - Review code syntax at specified line")
                report_lines.append("  - Check for missing brackets, quotes, or colons")
            elif error['error_type'] == 'APIError':
                report_lines.append("  - Verify API credentials in config")
                report_lines.append("  - Check API rate limits")
                report_lines.append("  - Confirm API endpoint is accessible")
            elif error['error_type'] in ['ValueError', 'TypeError']:
                report_lines.append("  - Review function arguments and types")
                report_lines.append("  - Add input validation")
            else:
                report_lines.append("  - Review error context and stack trace")
            
            report_lines.append("")
    
    report_lines.append("=" * 80)
    report_lines.append("END OF REPORT")
    report_lines.append("=" * 80)
    
    return "\n".join(report_lines)


def save_report(report):
    """
    Save diagnostic report to files.
    
    Args:
        report: Formatted report string
    """
    # Save text version
    report_path = 'logs/error_report.txt'
    try:
        with open(report_path, 'w') as f:
            f.write(report)
        logger.info(f"Report saved to {report_path}")
    except Exception as e:
        logger.error(f"Failed to save text report: {e}")
    
    # Save JSON version for dashboard
    json_path = 'logs/error_report.json'
    try:
        report_data = {
            'generated_at': datetime.now().isoformat(),
            'report_text': report
        }
        with open(json_path, 'w') as f:
            json.dump(report_data, f, indent=2)
        logger.info(f"JSON report saved to {json_path}")
    except Exception as e:
        logger.error(f"Failed to save JSON report: {e}")


def get_recent_errors(hours=24):
    """
    Only scan logs modified in the last N hours.
    
    Args:
        hours: Number of hours to look back
        
    Returns:
        dict: {log_file: [errors]} for recent errors only
    """
    cutoff_time = datetime.now() - timedelta(hours=hours)
    recent_errors = {}
    
    for log_dir in LOG_DIRECTORIES:
        if not os.path.exists(log_dir):
            continue
            
        log_files = glob.glob(os.path.join(log_dir, '*.log'))
        
        for log_file in log_files:
            # Check file modification time
            mod_time = datetime.fromtimestamp(os.path.getmtime(log_file))
            
            if mod_time >= cutoff_time:
                errors = scan_log_file(log_file)
                
                # Filter errors by timestamp if available
                filtered_errors = []
                for error in errors:
                    if error['timestamp']:
                        try:
                            error_time = datetime.strptime(error['timestamp'], '%Y-%m-%d %H:%M:%S')
                            if error_time >= cutoff_time:
                                filtered_errors.append(error)
                        except:
                            # If can't parse timestamp, include it
                            filtered_errors.append(error)
                    else:
                        # No timestamp, include if file is recent
                        filtered_errors.append(error)
                
                if filtered_errors:
                    recent_errors[log_file] = filtered_errors
    
    return recent_errors


def error_detective():
    """
    Main function - scan logs, identify errors, create report.
    
    Returns:
        int: Total error count
    """
    logger.info("Starting Error Detective scan...")
    
    # Scan all logs
    all_errors = scan_all_logs()
    
    if not all_errors:
        logger.info("No errors detected in logs!")
        return 0
    
    # Count total errors
    total_errors = sum(len(errs) for errs in all_errors.values())
    logger.info(f"Found {total_errors} errors across {len(all_errors)} log files")
    
    # Identify broken agents
    broken_agents = identify_broken_agents(all_errors)
    logger.warning(f"Broken agents detected: {list(broken_agents.keys())}")
    
    # Create diagnostic report
    report = create_diagnostic_report(all_errors)
    
    # Save report
    save_report(report)
    
    # Print summary
    print("\n" + "=" * 80)
    print("ERROR DETECTIVE SUMMARY")
    print("=" * 80)
    print(f"Total Errors: {total_errors}")
    print(f"Affected Agents: {len(broken_agents)}")
    print(f"Report saved to: logs/error_report.txt")
    print("=" * 80 + "\n")
    
    return total_errors


if __name__ == "__main__":
    error_count = error_detective()
    if error_count > 0:
        print(f"\n⚠️  {error_count} errors detected! Review logs/error_report.txt for details.")
    else:
        print("\n✅ No errors detected!")
