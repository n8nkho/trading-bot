#!/bin/bash
# start_bot.sh — reliable bot start/stop/restart/status
# Usage: ./start_bot.sh [start|stop|restart|status]
cd /home/ubuntu/trading-bot
PID_FILE="/home/ubuntu/trading-bot/main_loop.pid"
LOG_FILE="/home/ubuntu/trading-bot/logs/main_loop.log"
PYTHON="/home/ubuntu/trading-bot/venv/bin/python"
SCRIPT="/home/ubuntu/trading-bot/main_loop.py"

stop() {
    if [ -f "$PID_FILE" ]; then
        PID=$(cat "$PID_FILE")
        kill "$PID" 2>/dev/null && echo "Stopped PID $PID" || echo "Not running"
        rm -f "$PID_FILE"
    else
        pkill -f main_loop.py 2>/dev/null && echo "Stopped" || echo "Not running"
    fi
}

start() {
    if pgrep -f main_loop.py > /dev/null; then
        echo "Already running (PID $(pgrep -f main_loop.py))"
        return
    fi
    nohup "$PYTHON" "$SCRIPT" >> "$LOG_FILE" 2>&1 < /dev/null &
    echo $! > "$PID_FILE"
    sleep 2
    if pgrep -f main_loop.py > /dev/null; then
        echo "Started OK (PID $(cat $PID_FILE))"
    else
        echo "ERROR: failed to start — check $LOG_FILE"
    fi
}

status() {
    if pgrep -f main_loop.py > /dev/null; then
        echo "RUNNING (PID $(pgrep -f main_loop.py))"
    else
        echo "STOPPED"
    fi
}

case "${1:-start}" in
    start)   start ;;
    stop)    stop ;;
    restart) stop; sleep 2; start ;;
    status)  status ;;
    *) echo "Usage: $0 [start|stop|restart|status]" ;;
esac
