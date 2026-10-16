"""Explicit synthetic telemetry for development integration tests. Contains no ML values."""
import json
import os
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse, parse_qs

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)
        sequence = int(parse_qs(parsed.query).get("cursor", ["0"])[0]) + 1
        now = datetime.now(timezone.utc).isoformat()
        common = {"external_id": str(sequence), "observed_at": now, "mock": True}
        if parsed.path == "/equipment":
            records = [{**common, "object_id": 900001, "channel_id": 900001, "name": "ТЕСТ — синтетический датчик", "sensor_type": "temperature"}]
        elif parsed.path == "/telemetry":
            records = [{**common, "object_id": 900001, "channel_id": 900001, "event_id": sequence, "alarm": sequence % 10 == 0, "value": "25"}]
        elif parsed.path == "/ods":
            records = [{**common, "object_id":900001, "description":"ТЕСТ — запись диспетчерского журнала"}]
        elif parsed.path == "/weather":
            records = [{**common, "longitude":37.61, "latitude":55.75, "temperature":12, "humidity":65, "pressure":1013}]
        elif parsed.path == "/work_status":
            request_id = int(os.environ.get("MOCK_REQUEST_ID", "0"))
            records = [{**common, "request_id":request_id, "status":"in_progress"}] if request_id else []
        else:
            self.send_error(404); return
        body = json.dumps({"records": records, "next_cursor": str(sequence)}).encode()
        self.send_response(200); self.send_header("Content-Type", "application/json"); self.end_headers(); self.wfile.write(body)

if __name__ == "__main__":
    HTTPServer(("0.0.0.0", 8091), Handler).serve_forever()
