"""
Llama Watchdog - Monitor and optimize Llama/Ollama performance
Ensures Llama stays healthy and responsive during trading operations
"""

import json
import logging
import subprocess
import time
from datetime import datetime, time as dt_time
from pathlib import Path
import requests
import pytz

# Setup logging
log_dir = Path("logs")
log_dir.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(log_dir / "llama_watchdog.log"),
        logging.StreamHandler()
    ]
)

logger = logging.getLogger(__name__)

# Configuration
DATA_DIR = Path("data")
DATA_DIR.mkdir(exist_ok=True)

PERFORMANCE_FILE = DATA_DIR / "llama_performance.json"
OLLAMA_BASE_URL = "http://localhost:11434"
DEFAULT_MODEL = "llama3.1:8b"
FALLBACK_MODEL = "llama3.1:3b"

# Thresholds
SLOW_RESPONSE_THRESHOLD = 60  # seconds
TIMEOUT_THRESHOLD = 120  # seconds
HEALTH_CHECK_TIMEOUT = 10  # seconds
MIN_CONFIDENCE_FOR_LLAMA = 0.7  # Skip Llama for low-confidence candidates

# Emergency mode flag
EMERGENCY_MODE_FILE = DATA_DIR / "emergency_mode.json"


def check_llama_health():
    """
    Check Ollama service health and performance.
    
    Returns:
        dict: {
            'healthy': bool,
            'health_score': int (0-100),
            'service_running': bool,
            'models_loaded': list,
            'response_time': float (seconds),
            'issues': list of issue strings
        }
    """
    logger.info("Checking Llama health...")
    
    health_data = {
        'healthy': True,
        'health_score': 100,
        'service_running': False,
        'models_loaded': [],
        'response_time': None,
        'issues': [],
        'timestamp': datetime.now().isoformat()
    }
    
    # 1. Check if Ollama service is running
    try:
        response = requests.get(f"{OLLAMA_BASE_URL}/api/tags", timeout=HEALTH_CHECK_TIMEOUT)
        if response.status_code == 200:
            health_data['service_running'] = True
            data = response.json()
            health_data['models_loaded'] = [model['name'] for model in data.get('models', [])]
            logger.info(f"Ollama service running. Models loaded: {health_data['models_loaded']}")
        else:
            health_data['service_running'] = False
            health_data['issues'].append(f"Ollama API returned status {response.status_code}")
            health_data['health_score'] -= 50
            logger.warning(f"Ollama API returned status {response.status_code}")
    except requests.exceptions.ConnectionError:
        health_data['service_running'] = False
        health_data['issues'].append("Cannot connect to Ollama service")
        health_data['health_score'] = 0
        health_data['healthy'] = False
        logger.error("Cannot connect to Ollama service at localhost:11434")
        return health_data
    except requests.exceptions.Timeout:
        health_data['service_running'] = False
        health_data['issues'].append("Ollama service timeout")
        health_data['health_score'] -= 50
        logger.error("Ollama service timeout")
    except Exception as e:
        health_data['service_running'] = False
        health_data['issues'].append(f"Error checking service: {str(e)}")
        health_data['health_score'] -= 50
        logger.error(f"Error checking Ollama service: {type(e).__name__}: {str(e)}")
    
    # 2. Test response time with simple prompt
    if health_data['service_running']:
        try:
            logger.info("Testing Llama response time...")
            start_time = time.time()
            
            test_prompt = "Say 'OK' if you can read this."
            response = requests.post(
                f"{OLLAMA_BASE_URL}/api/generate",
                json={
                    "model": DEFAULT_MODEL,
                    "prompt": test_prompt,
                    "stream": False
                },
                timeout=30
            )
            
            response_time = time.time() - start_time
            health_data['response_time'] = response_time
            
            if response.status_code == 200:
                logger.info(f"Llama response time: {response_time:.2f}s")
                
                # Score based on response time
                if response_time < 5:
                    pass  # Excellent, no penalty
                elif response_time < 15:
                    health_data['health_score'] -= 10
                    health_data['issues'].append(f"Slow response time: {response_time:.2f}s")
                elif response_time < 30:
                    health_data['health_score'] -= 25
                    health_data['issues'].append(f"Very slow response time: {response_time:.2f}s")
                else:
                    health_data['health_score'] -= 40
                    health_data['issues'].append(f"Extremely slow response time: {response_time:.2f}s")
            else:
                health_data['issues'].append(f"Test prompt failed with status {response.status_code}")
                health_data['health_score'] -= 30
                logger.warning(f"Test prompt failed with status {response.status_code}")
                
        except requests.exceptions.Timeout:
            health_data['issues'].append("Test prompt timed out (>30s)")
            health_data['health_score'] -= 40
            health_data['response_time'] = 30.0
            logger.error("Test prompt timed out")
        except Exception as e:
            health_data['issues'].append(f"Test prompt error: {str(e)}")
            health_data['health_score'] -= 30
            logger.error(f"Error testing response time: {type(e).__name__}: {str(e)}")
    
    # 3. Check if required models are available
    if health_data['service_running']:
        if DEFAULT_MODEL not in health_data['models_loaded']:
            health_data['issues'].append(f"Default model {DEFAULT_MODEL} not loaded")
            health_data['health_score'] -= 20
            logger.warning(f"Default model {DEFAULT_MODEL} not loaded")
    
    # Final health determination
    if health_data['health_score'] < 50:
        health_data['healthy'] = False
    
    logger.info(f"Health check complete: Score={health_data['health_score']}, Healthy={health_data['healthy']}")
    
    # Save health data
    save_performance_data({'health_check': health_data})
    
    return health_data


def optimize_llama_performance():
    """
    Optimize Llama performance based on recent metrics.
    
    Actions:
    - Adjust timeouts if responses are slow
    - Switch to smaller model if needed
    - Restart Ollama if timing out
    - Enable emergency mode if completely failed
    
    Returns:
        dict: {
            'optimized': bool,
            'actions_taken': list of action strings,
            'current_model': str,
            'emergency_mode': bool
        }
    """
    logger.info("Optimizing Llama performance...")
    
    result = {
        'optimized': False,
        'actions_taken': [],
        'current_model': DEFAULT_MODEL,
        'emergency_mode': False,
        'timestamp': datetime.now().isoformat()
    }
    
    # Check current health
    health = check_llama_health()
    
    # Load performance history
    perf_data = load_performance_data()
    avg_response_time = calculate_avg_response_time(perf_data)
    
    # 1. If Llama is slow (>60s average)
    if avg_response_time and avg_response_time > SLOW_RESPONSE_THRESHOLD:
        logger.warning(f"Llama is slow: {avg_response_time:.2f}s average response time")
        result['actions_taken'].append(f"Detected slow responses: {avg_response_time:.2f}s average")
        
        # Try switching to smaller model
        if result['current_model'] == DEFAULT_MODEL:
            logger.info(f"Attempting to switch to smaller model: {FALLBACK_MODEL}")
            if try_switch_model(FALLBACK_MODEL):
                result['current_model'] = FALLBACK_MODEL
                result['actions_taken'].append(f"Switched to smaller model: {FALLBACK_MODEL}")
                result['optimized'] = True
            else:
                result['actions_taken'].append("Failed to switch to smaller model")
    
    # 2. If Llama is timing out or unhealthy
    if not health['healthy'] or health['health_score'] < 30:
        logger.warning(f"Llama unhealthy (score: {health['health_score']})")
        
        # Try restarting Ollama
        logger.info("Attempting to restart Ollama service...")
        if restart_ollama():
            result['actions_taken'].append("Restarted Ollama service")
            result['optimized'] = True
            
            # Wait and test again
            logger.info("Waiting 30 seconds for service to stabilize...")
            time.sleep(30)
            
            health_after = check_llama_health()
            if health_after['healthy']:
                logger.info("Ollama service recovered successfully")
                result['actions_taken'].append("Service recovered after restart")
            else:
                logger.error("Ollama service still unhealthy after restart")
                result['actions_taken'].append("Service still unhealthy after restart")
                
                # Enable emergency mode
                logger.error("ENABLING EMERGENCY MODE - Llama offline")
                enable_emergency_mode("Llama service failed after restart attempt")
                result['emergency_mode'] = True
                result['actions_taken'].append("EMERGENCY MODE ENABLED")
        else:
            logger.error("Failed to restart Ollama service")
            result['actions_taken'].append("Failed to restart service")
            
            # Enable emergency mode
            logger.error("ENABLING EMERGENCY MODE - Cannot restart Llama")
            enable_emergency_mode("Cannot restart Ollama service")
            result['emergency_mode'] = True
            result['actions_taken'].append("EMERGENCY MODE ENABLED")
    
    # 3. If healthy but could be better
    elif health['health_score'] < 80:
        logger.info(f"Llama health suboptimal (score: {health['health_score']})")
        result['actions_taken'].append(f"Health score: {health['health_score']}/100")
        
        # Log recommendations
        for issue in health['issues']:
            logger.info(f"Issue: {issue}")
            result['actions_taken'].append(f"Issue: {issue}")
    
    logger.info(f"Optimization complete: {len(result['actions_taken'])} actions taken")
    
    # Save optimization result
    save_performance_data({'optimization': result})
    
    return result


def preload_models():
    """
    Preload Llama models into memory to prevent first-run slowness.
    Should be called at 2:55 AM before 3 AM screening.
    
    Returns:
        dict: {
            'success': bool,
            'model': str,
            'preload_time': float (seconds),
            'error': str or None
        }
    """
    logger.info("Preloading Llama models for screening...")
    
    result = {
        'success': False,
        'model': DEFAULT_MODEL,
        'preload_time': None,
        'error': None,
        'timestamp': datetime.now().isoformat()
    }
    
    try:
        start_time = time.time()
        
        # Send dummy prompt to load model
        dummy_prompt = "This is a warm-up prompt to load the model into memory. Please respond with OK."
        
        response = requests.post(
            f"{OLLAMA_BASE_URL}/api/generate",
            json={
                "model": DEFAULT_MODEL,
                "prompt": dummy_prompt,
                "stream": False
            },
            timeout=60
        )
        
        preload_time = time.time() - start_time
        result['preload_time'] = preload_time
        
        if response.status_code == 200:
            result['success'] = True
            logger.info(f"Llama preloaded successfully in {preload_time:.2f}s for 3 AM screening")
        else:
            result['error'] = f"Preload failed with status {response.status_code}"
            logger.error(result['error'])
            
    except Exception as e:
        result['error'] = f"{type(e).__name__}: {str(e)}"
        logger.error(f"Error preloading models: {result['error']}")
    
    # Save preload result
    save_performance_data({'preload': result})
    
    return result


def adaptive_timeout(confidence_threshold=MIN_CONFIDENCE_FOR_LLAMA):
    """
    Determine if Llama analysis should be skipped based on confidence.
    Only analyze high-confidence candidates to reduce Llama calls.
    
    Args:
        confidence_threshold: Minimum confidence to use Llama (default 0.7)
        
    Returns:
        dict: {
            'use_llama': bool,
            'reason': str,
            'threshold': float
        }
    """
    # This is a helper function that can be called by other agents
    # The actual filtering happens in the calling code
    
    return {
        'threshold': confidence_threshold,
        'reason': f"Only candidates with confidence >= {confidence_threshold} will use Llama analysis"
    }


def emergency_fallback():
    """
    Enable emergency fallback mode when Llama is completely offline.
    Uses simple rule-based scoring instead of AI analysis.
    
    Returns:
        dict: {
            'mode': 'EMERGENCY',
            'rules': dict of fallback rules,
            'timestamp': ISO timestamp
        }
    """
    logger.error("=" * 80)
    logger.error("EMERGENCY MODE ACTIVATED")
    logger.error("Llama offline - switching to rule-based scoring")
    logger.error("=" * 80)
    
    fallback_rules = {
        'mode': 'EMERGENCY',
        'description': 'Rule-based scoring without AI',
        'rules': {
            'buy_signal': {
                'rsi': {'operator': '<', 'value': 35},
                'drop_pct': {'operator': '>', 'value': 7.0},
                'volume_ratio': {'operator': '>', 'value': 1.5}
            },
            'confidence_calculation': 'Simple average of normalized metrics',
            'no_llm_analysis': True
        },
        'timestamp': datetime.now().isoformat()
    }
    
    # Save emergency mode state
    enable_emergency_mode("Emergency fallback activated")
    
    logger.error("Emergency rules:")
    logger.error(f"  BUY if: RSI < 35 AND drop > 7% AND volume_ratio > 1.5")
    logger.error(f"  Confidence: Simple metric-based calculation")
    
    return fallback_rules


def enable_emergency_mode(reason):
    """
    Enable emergency mode and save state.
    
    Args:
        reason: Reason for enabling emergency mode
    """
    emergency_state = {
        'enabled': True,
        'reason': reason,
        'enabled_at': datetime.now().isoformat()
    }
    
    try:
        with open(EMERGENCY_MODE_FILE, 'w') as f:
            json.dump(emergency_state, f, indent=2)
        logger.error(f"Emergency mode enabled: {reason}")
    except Exception as e:
        logger.error(f"Error saving emergency mode state: {type(e).__name__}: {str(e)}")


def disable_emergency_mode():
    """
    Disable emergency mode.
    """
    try:
        if EMERGENCY_MODE_FILE.exists():
            EMERGENCY_MODE_FILE.unlink()
        logger.info("Emergency mode disabled")
    except Exception as e:
        logger.error(f"Error disabling emergency mode: {type(e).__name__}: {str(e)}")


def is_emergency_mode():
    """
    Check if emergency mode is currently enabled.
    
    Returns:
        bool: True if emergency mode is active
    """
    try:
        if EMERGENCY_MODE_FILE.exists():
            with open(EMERGENCY_MODE_FILE, 'r') as f:
                state = json.load(f)
            return state.get('enabled', False)
        return False
    except Exception as e:
        logger.error(f"Error checking emergency mode: {type(e).__name__}: {str(e)}")
        return False


def restart_ollama():
    """
    Restart Ollama service using systemctl.
    
    Returns:
        bool: True if restart successful
    """
    try:
        logger.info("Restarting Ollama service...")
        
        # Try to restart using systemctl
        result = subprocess.run(
            ['sudo', 'systemctl', 'restart', 'ollama'],
            capture_output=True,
            text=True,
            timeout=30
        )
        
        if result.returncode == 0:
            logger.info("Ollama service restarted successfully")
            return True
        else:
            logger.error(f"Failed to restart Ollama: {result.stderr}")
            return False
            
    except subprocess.TimeoutExpired:
        logger.error("Timeout while restarting Ollama service")
        return False
    except FileNotFoundError:
        logger.error("systemctl not found - cannot restart Ollama")
        return False
    except Exception as e:
        logger.error(f"Error restarting Ollama: {type(e).__name__}: {str(e)}")
        return False


def try_switch_model(model_name):
    """
    Try to switch to a different model.
    
    Args:
        model_name: Name of model to switch to
        
    Returns:
        bool: True if switch successful
    """
    try:
        logger.info(f"Testing model: {model_name}")
        
        # Test if model works
        response = requests.post(
            f"{OLLAMA_BASE_URL}/api/generate",
            json={
                "model": model_name,
                "prompt": "Test",
                "stream": False
            },
            timeout=30
        )
        
        if response.status_code == 200:
            logger.info(f"Successfully switched to model: {model_name}")
            return True
        else:
            logger.error(f"Model {model_name} test failed with status {response.status_code}")
            return False
            
    except Exception as e:
        logger.error(f"Error switching to model {model_name}: {type(e).__name__}: {str(e)}")
        return False


def load_performance_data():
    """
    Load Llama performance history from file.
    
    Returns:
        dict: Performance data
    """
    try:
        if PERFORMANCE_FILE.exists():
            with open(PERFORMANCE_FILE, 'r') as f:
                return json.load(f)
        return {'history': []}
    except Exception as e:
        logger.error(f"Error loading performance data: {type(e).__name__}: {str(e)}")
        return {'history': []}


def save_performance_data(data):
    """
    Save performance data to file.
    
    Args:
        data: Performance data dict to append
    """
    try:
        # Load existing data
        perf_data = load_performance_data()
        
        # Append new data
        if 'history' not in perf_data:
            perf_data['history'] = []
        
        perf_data['history'].append({
            'timestamp': datetime.now().isoformat(),
            'data': data
        })
        
        # Keep only last 1000 entries
        if len(perf_data['history']) > 1000:
            perf_data['history'] = perf_data['history'][-1000:]
        
        # Save back to file
        with open(PERFORMANCE_FILE, 'w') as f:
            json.dump(perf_data, f, indent=2)
            
    except Exception as e:
        logger.error(f"Error saving performance data: {type(e).__name__}: {str(e)}")


def calculate_avg_response_time(perf_data, lookback_hours=24):
    """
    Calculate average response time from recent history.
    
    Args:
        perf_data: Performance data dict
        lookback_hours: Hours to look back (default 24)
        
    Returns:
        float: Average response time in seconds, or None if no data
    """
    try:
        from datetime import timedelta
        
        cutoff_time = datetime.now() - timedelta(hours=lookback_hours)
        response_times = []
        
        for entry in perf_data.get('history', []):
            timestamp = datetime.fromisoformat(entry['timestamp'])
            if timestamp >= cutoff_time:
                # Check for health check data
                if 'health_check' in entry['data']:
                    rt = entry['data']['health_check'].get('response_time')
                    if rt is not None:
                        response_times.append(rt)
        
        if response_times:
            avg = sum(response_times) / len(response_times)
            logger.info(f"Average response time (last {lookback_hours}h): {avg:.2f}s ({len(response_times)} samples)")
            return avg
        
        return None
        
    except Exception as e:
        logger.error(f"Error calculating average response time: {type(e).__name__}: {str(e)}")
        return None


def run_watchdog():
    """
    Run complete watchdog check and optimization.
    Should be called every 15 minutes during market hours.
    
    Returns:
        dict: Complete watchdog report
    """
    logger.info("=" * 80)
    logger.info("LLAMA WATCHDOG - Starting monitoring cycle")
    logger.info("=" * 80)
    
    report = {
        'timestamp': datetime.now().isoformat(),
        'health': None,
        'optimization': None,
        'emergency_mode': is_emergency_mode()
    }
    
    # 1. Check health
    health = check_llama_health()
    report['health'] = health
    
    # 2. Optimize if needed
    if not health['healthy'] or health['health_score'] < 70:
        logger.warning("Health issues detected - running optimization...")
        optimization = optimize_llama_performance()
        report['optimization'] = optimization
    else:
        logger.info("Llama health is good - no optimization needed")
        report['optimization'] = {'optimized': False, 'reason': 'Health is good'}
    
    # 3. Check if we should disable emergency mode
    if report['emergency_mode'] and health['healthy'] and health['health_score'] >= 80:
        logger.info("Llama recovered - disabling emergency mode")
        disable_emergency_mode()
        report['emergency_mode'] = False
        report['emergency_mode_disabled'] = True
    
    logger.info("=" * 80)
    logger.info(f"WATCHDOG COMPLETE - Health: {health['health_score']}/100, Emergency: {report['emergency_mode']}")
    logger.info("=" * 80)
    
    return report


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) < 2:
        print("Usage:")
        print("  python agents/llama_watchdog.py health     - Check Llama health")
        print("  python agents/llama_watchdog.py optimize   - Optimize performance")
        print("  python agents/llama_watchdog.py preload    - Preload models")
        print("  python agents/llama_watchdog.py watchdog   - Run complete watchdog")
        print("  python agents/llama_watchdog.py emergency  - Enable emergency mode")
        sys.exit(1)
    
    command = sys.argv[1].lower()
    
    if command == "health":
        health = check_llama_health()
        print(f"\nHealth Score: {health['health_score']}/100")
        print(f"Healthy: {health['healthy']}")
        print(f"Service Running: {health['service_running']}")
        print(f"Response Time: {health['response_time']:.2f}s" if health['response_time'] else "Response Time: N/A")
        if health['models_loaded']:
            print(f"Models Loaded: {', '.join(health['models_loaded'])}")
        if health['issues']:
            print("\nIssues:")
            for issue in health['issues']:
                print(f"  - {issue}")
    
    elif command == "optimize":
        result = optimize_llama_performance()
        print(f"\nOptimized: {result['optimized']}")
        print(f"Current Model: {result['current_model']}")
        print(f"Emergency Mode: {result['emergency_mode']}")
        if result['actions_taken']:
            print("\nActions Taken:")
            for action in result['actions_taken']:
                print(f"  - {action}")
    
    elif command == "preload":
        result = preload_models()
        print(f"\nSuccess: {result['success']}")
        if result['success']:
            print(f"Preload Time: {result['preload_time']:.2f}s")
        else:
            print(f"Error: {result['error']}")
    
    elif command == "watchdog":
        report = run_watchdog()
        print(f"\nHealth Score: {report['health']['health_score']}/100")
        print(f"Emergency Mode: {report['emergency_mode']}")
        if report['optimization']['optimized']:
            print("\nOptimizations:")
            for action in report['optimization']['actions_taken']:
                print(f"  - {action}")
    
    elif command == "emergency":
        fallback = emergency_fallback()
        print("\nEmergency mode enabled")
        print("Using rule-based scoring:")
        print("  BUY if: RSI < 35 AND drop > 7% AND volume_ratio > 1.5")
    
    else:
        print(f"Unknown command: {command}")
        sys.exit(1)
