#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

case "${1:-help}" in
  server-start)
    echo "Starting DCSS server..."
    docker run -d --name dcss-webtiles -p 8080:8080 ghcr.io/nkhoit/dcss-webtiles:latest
    echo "Waiting for server..."
    python3 -c "
import time
try:
    import websockets.sync.client as ws
except ImportError:
    print('Installing websockets...'); import subprocess; subprocess.check_call(['pip', 'install', 'websockets', '-q'])
    import websockets.sync.client as ws
for i in range(60):
    try:
        c = ws.connect('ws://localhost:8080/socket', open_timeout=2)
        c.close()
        print(f'Server ready ({i+1}s)')
        break
    except Exception:
        time.sleep(1)
else:
    raise RuntimeError('Server failed to start')
"
    ;;
  server-stop)
    echo "Stopping DCSS server..."
    docker stop dcss-webtiles && docker rm dcss-webtiles
    ;;
  test)
    echo "Running integration tests..."
    python3 -m pytest tests/test_integration.py -v "$@"
    ;;
  help|*)
    echo "Usage: ./run.sh <command>"
    echo ""
    echo "Commands:"
    echo "  server-start   Start the DCSS webtiles server (Docker)"
    echo "  server-stop    Stop the DCSS server"
    echo "  test           Run integration tests (server must be running)"
    ;;
esac
