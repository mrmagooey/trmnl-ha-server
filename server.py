import http.server
import socketserver
import json

PORT = 8000

class APICalls(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/api/setup':
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            response = {"status": "setup complete"}
            self.wfile.write(json.dumps(response).encode('utf-8'))
            return

        if self.path == '/api/display':
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            response = {"data": "some data to display"}
            self.wfile.write(json.dumps(response).encode('utf-8'))
            return

        self.send_response(404)
        self.send_header('Content-type', 'text/plain')
        self.end_headers()
        self.wfile.write(b'Not Found')


with socketserver.TCPServer(("", PORT), APICalls) as httpd:
    print("serving at port", PORT)
    httpd.serve_forever()
