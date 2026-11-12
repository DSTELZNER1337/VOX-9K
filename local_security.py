"""Small loopback HTTP guards; local CLI clients may omit Origin."""
MAX_REQUEST_BYTES = 64 * 1024
UI_ORIGINS = {'http://127.0.0.1:5000', 'http://localhost:5000'}


def permitted_request(headers, port):
    hosts = {f'{name}:{port}' for name in ('localhost', '127.0.0.1')}
    hosts.update({'localhost', '127.0.0.1'})
    if headers.get('host', '').lower() not in hosts:
        return False
    origin = headers.get('origin')
    if origin is not None and origin not in UI_ORIGINS:
        return False
    return headers.get('sec-fetch-site') != 'cross-site'


class LocalOnlyMiddleware:
    """ASGI guard with a bounded body before JSON parsing (including chunked HTTP)."""
    def __init__(self, app, port):
        self.app, self.port = app, port

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http':
            return await self.app(scope, receive, send)
        from starlette.responses import JSONResponse
        headers = {k.decode('latin1'): v.decode('latin1') for k, v in scope['headers']}
        if not permitted_request(headers, self.port):
            return await JSONResponse({'detail': 'Local application requests only.'}, status_code=403)(scope, receive, send)
        if scope['method'] == 'POST':
            body = bytearray()
            while True:
                message = await receive()
                if message['type'] == 'http.disconnect':
                    return
                body.extend(message.get('body', b''))
                if len(body) > MAX_REQUEST_BYTES:
                    return await JSONResponse({'detail': 'Request body is too large.'}, status_code=413)(scope, receive, send)
                if not message.get('more_body', False):
                    break
            delivered = False
            upstream_receive = receive
            async def bounded_receive():
                nonlocal delivered
                if not delivered:
                    delivered = True
                    return {'type': 'http.request', 'body': bytes(body), 'more_body': False}
                return await upstream_receive()
            receive = bounded_receive
        return await self.app(scope, receive, send)
