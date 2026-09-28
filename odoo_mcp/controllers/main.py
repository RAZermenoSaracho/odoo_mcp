import json

from werkzeug.exceptions import Forbidden, UnsupportedMediaType

from odoo import http
from odoo.http import Response, request

from .. import protocol, ratelimit

# Dispatcher spike (Odoo 19, 2026-09-27): a `type='http'`, `auth='bearer'`,
# `csrf=False` route is reached with the API key owner's env (su False); a
# missing/invalid key gives 401 + `WWW-Authenticate: Bearer`; 405/413 and 401
# bodies are plain werkzeug pages without tracebacks. (`type='json2'` was
# rejected: its error handler attaches a `debug` traceback to every error.)


class McpController(http.Controller):

    @http.route(
        '/mcp',
        type='http',
        auth='bearer',
        methods=['POST'],
        csrf=False,
        save_session=False,
        max_content_length=2 * 1024 * 1024,
    )
    def mcp(self):
        httprequest = request.httprequest
        allowed, retry_after = ratelimit.LIMITER.check((request.env.cr.dbname, request.env.uid))
        if not allowed:
            return request.make_json_response(
                protocol.error_body(None, protocol.RATE_LIMITED, "Rate limit exceeded"),
                headers=[('Retry-After', str(retry_after))], status=429)
        origin = httprequest.headers.get('Origin')
        if origin is not None and origin.rstrip('/') != httprequest.host_url.rstrip('/'):
            raise Forbidden("Origin not allowed")
        if httprequest.mimetype != 'application/json':
            raise UnsupportedMediaType("Content-Type must be application/json")
        try:
            message = json.loads(httprequest.get_data())
        except ValueError:
            return request.make_json_response(
                protocol.error_body(None, protocol.PARSE_ERROR, "Parse error"), status=400)
        status, body = protocol.handle_message(message, httprequest.headers, request.env)
        if body is None:
            return Response(status=status)
        return request.make_json_response(body, status=status)
