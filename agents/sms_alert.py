"""
SMS Alert Agent - Send SMS notifications for critical system failures

Purpose: Alert via SMS when critical errors occur that auto-healing can't fix
Conservative approach: Max 5 alerts per day, only for critical failures
"""

import os
import logging
import json
from datetime import datetime, timedelta
from twilio.rest import Client

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('logs/sms_alert.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Twilio config (from environment)
TWILIO_ACCOUNT_SID = os.getenv('TWILIO_ACCOUNT_SID')
TWILIO_AUTH_TOKEN = os.getenv('TWILIO_AUTH_TOKEN')
TWILIO_FROM_NUMBER = os.getenv('TWILIO_FROM_NUMBER')  # Your Twilio number
ALERT_TO_NUMBER = os.getenv('ALERT_TO_NUMBER')        # Your personal number

# Alert thresholds
MAX_ALERTS_PER_DAY = 5
ALERT_LOG_FILE = 'logs/sms_alerts.json'

# Critical error types
CRITICAL_ERRORS = {
    'SCREENER_MISSED': 'Daily screener failed to run',
    'DASHBOARD_DOWN': 'Dashboard crashed 3+ times',
    'OLLAMA_DEAD': 'Ollama service unresponsive',
    'ALL_CRONS_STOPPED': 'All cron jobs stopped',
    'TRADE_EXECUTION_FAILED': 'Failed to execute critical trade',
    'SYSTEM_FAILURE': 'Multiple agents down'
}


def load_alert_history():
    """
    Load alert history from JSON file.
    
    Returns:
        list: Alerts sent today
    """
    try:
        if not os.path.exists(ALERT_LOG_FILE):
            os.makedirs(os.path.dirname(ALERT_LOG_FILE), exist_ok=True)
            with open(ALERT_LOG_FILE, 'w') as f:
                json.dump([], f)
            return []
        
        with open(ALERT_LOG_FILE, 'r') as f:
            all_alerts = json.load(f)
        
        # Filter to today's alerts only
        today = datetime.now().date()
        today_alerts = [
            alert for alert in all_alerts
            if datetime.fromisoformat(alert['timestamp']).date() == today
        ]
        
        logger.info(f"Loaded {len(today_alerts)} alerts sent today")
        return today_alerts
        
    except Exception as e:
        logger.error(f"Error loading alert history: {e}")
        return []


def save_alert_history(alert_data):
    """
    Append alert to history file.
    
    Args:
        alert_data (dict): Alert details to save
    """
    try:
        # Load existing alerts
        if os.path.exists(ALERT_LOG_FILE):
            with open(ALERT_LOG_FILE, 'r') as f:
                alerts = json.load(f)
        else:
            alerts = []
        
        # Append new alert
        alerts.append(alert_data)
        
        # Keep only last 30 days of alerts
        cutoff_date = datetime.now() - timedelta(days=30)
        alerts = [
            alert for alert in alerts
            if datetime.fromisoformat(alert['timestamp']) > cutoff_date
        ]
        
        # Save back to file
        with open(ALERT_LOG_FILE, 'w') as f:
            json.dump(alerts, f, indent=2)
        
        logger.info(f"Saved alert to history: {alert_data['error_type']}")
        
    except Exception as e:
        logger.error(f"Error saving alert history: {e}")


def can_send_alert():
    """
    Check if we're under the daily alert limit.
    
    Returns:
        bool: True if can send, False if limit reached
    """
    try:
        today_alerts = load_alert_history()
        
        if len(today_alerts) >= MAX_ALERTS_PER_DAY:
            logger.warning(f"Daily alert limit reached ({MAX_ALERTS_PER_DAY}). Skipping SMS.")
            return False
        
        return True
        
    except Exception as e:
        logger.error(f"Error checking alert limit: {e}")
        return False


def format_alert_message(error_type, details):
    """
    Format a concise SMS alert message (max 160 chars).
    
    Args:
        error_type (str): Type of critical error
        details (str): Additional details
        
    Returns:
        str: Formatted SMS message
    """
    timestamp = datetime.now().strftime("%H:%M")
    
    # Base message
    base = f"FORTRESS ALERT [{timestamp}]: {error_type}"
    
    # Add details if space allows
    if details:
        max_detail_len = 160 - len(base) - 3  # -3 for " - "
        if len(details) > max_detail_len:
            details = details[:max_detail_len-3] + "..."
        message = f"{base} - {details}"
    else:
        message = base
    
    return message[:160]  # Ensure max 160 chars


def send_sms(message, error_type):
    """
    Send SMS via Twilio.
    
    Args:
        message (str): SMS message to send
        error_type (str): Type of error for logging
        
    Returns:
        bool: True if sent successfully, False otherwise
    """
    try:
        # Check if Twilio is configured
        if not all([TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_FROM_NUMBER, ALERT_TO_NUMBER]):
            logger.warning("Twilio not configured. Skipping SMS. Set environment variables:")
            logger.warning("TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_FROM_NUMBER, ALERT_TO_NUMBER")
            return False
        
        # Check daily limit
        if not can_send_alert():
            return False
        
        # Send SMS
        client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
        sms = client.messages.create(
            body=message,
            from_=TWILIO_FROM_NUMBER,
            to=ALERT_TO_NUMBER
        )
        
        logger.info(f"SMS sent successfully. SID: {sms.sid}")
        
        # Save to history
        alert_data = {
            'timestamp': datetime.now().isoformat(),
            'error_type': error_type,
            'message': message,
            'sms_sid': sms.sid
        }
        save_alert_history(alert_data)
        
        return True
        
    except Exception as e:
        logger.error(f"Error sending SMS: {e}")
        return False


def alert_critical_failure(error_type, details=None):
    """
    Main function to send critical failure alerts.
    
    Args:
        error_type (str): Must be one of CRITICAL_ERRORS keys
        details (str, optional): Additional context
        
    Returns:
        bool: True if alert sent, False if skipped
    """
    try:
        # Validate error type
        if error_type not in CRITICAL_ERRORS:
            logger.error(f"Invalid error type: {error_type}. Must be one of {list(CRITICAL_ERRORS.keys())}")
            return False
        
        # Get error description
        error_desc = CRITICAL_ERRORS[error_type]
        
        # Use details if provided, otherwise use default description
        message_details = details if details else error_desc
        
        # Format message
        message = format_alert_message(error_type, message_details)
        
        logger.info(f"Attempting to send critical alert: {error_type}")
        logger.info(f"Message: {message}")
        
        # Send SMS
        success = send_sms(message, error_type)
        
        if success:
            logger.info(f"Critical alert sent successfully: {error_type}")
        else:
            logger.warning(f"Critical alert not sent: {error_type}")
        
        return success
        
    except Exception as e:
        logger.error(f"Error in alert_critical_failure: {e}")
        return False


def test_sms():
    """
    Send a test SMS to verify Twilio configuration.
    
    Returns:
        bool: True if test successful, False otherwise
    """
    try:
        logger.info("Sending test SMS...")
        
        # Check configuration
        if not all([TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_FROM_NUMBER, ALERT_TO_NUMBER]):
            logger.error("Twilio not configured. Set these environment variables:")
            logger.error("  TWILIO_ACCOUNT_SID")
            logger.error("  TWILIO_AUTH_TOKEN")
            logger.error("  TWILIO_FROM_NUMBER")
            logger.error("  ALERT_TO_NUMBER")
            return False
        
        # Send test message
        test_message = f"FORTRESS TEST [{datetime.now().strftime('%H:%M')}]: SMS alerts working correctly"
        
        client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
        sms = client.messages.create(
            body=test_message,
            from_=TWILIO_FROM_NUMBER,
            to=ALERT_TO_NUMBER
        )
        
        logger.info(f"Test SMS sent successfully! SID: {sms.sid}")
        logger.info(f"Message: {test_message}")
        
        return True
        
    except Exception as e:
        logger.error(f"Test SMS failed: {e}")
        return False


if __name__ == "__main__":
    # Run test when executed directly
    print("Testing SMS Alert System...")
    print("-" * 50)
    
    success = test_sms()
    
    if success:
        print("\n✓ SMS alert system is working!")
    else:
        print("\n✗ SMS alert system test failed. Check logs/sms_alert.log")
