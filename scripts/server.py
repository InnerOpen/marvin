"""
License: MIT License
Copyright (c) 2023 Miel Donkers

Very simple HTTP server in python for logger requests
Usage::
    ./server.py [<port>]
"""

from http.server import BaseHTTPRequestHandler, HTTPServer

from marvin.core.root_logger import get_logger

logger = get_logger("server")


class S(BaseHTTPRequestHandler):
    def _set_response(self):
        self.send_response(200)
        self.send_header("Content-type", "text/html")
        self.end_headers()

    def do_GET(self):
        logger.info("GET request,\nPath: %s\nHeaders:\n%s\n", str(self.path), str(self.headers))
        self._set_response()
        self.wfile.write(f"GET request for {self.path}".encode())

    def do_DELETE(self):
        logger.info("DELETE request,\nPath: %s\nHeaders:\n%s\n", str(self.path), str(self.headers))
        self._set_response()
        self.wfile.write(f"DELETE request for {self.path}".encode())

    def do_PUT(self):
        content_length = int(self.headers["Content-Length"])  # <--- Gets the size of data
        put_data = self.rfile.read(content_length)  # <--- Gets the data itself
        logger.info(
            "PUT request,\nPath: %s\nHeaders:\n%s\n\nBody:\n%s\n",
            str(self.path),
            str(self.headers),
            put_data.decode("utf-8"),
        )

        self._set_response()
        self.wfile.write(f"PUT request for {self.path}".encode())

    def do_POST(self):
        content_length = int(self.headers["Content-Length"])  # <--- Gets the size of data
        post_data = self.rfile.read(content_length)  # <--- Gets the data itself
        logger.info(
            "POST request,\nPath: %s\nHeaders:\n%s\n\nBody:\n%s\n",
            str(self.path),
            str(self.headers),
            post_data.decode("utf-8"),
        )

        self._set_response()
        self.wfile.write(f"POST request for {self.path}".encode())


def run(server_class=HTTPServer, handler_class=S, port=8080):
    server_address = ("", port)
    httpd = server_class(server_address, handler_class)
    logger.info("Starting httpd...\n")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    httpd.server_close()
    logger.info("Stopping httpd...\n")


if __name__ == "__main__":
    from sys import argv

    if len(argv) == 2:
        run(port=int(argv[1]))
    else:
        run()
