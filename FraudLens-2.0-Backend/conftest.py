"""Network isolation applies before collection, including with a developer key.

MockTransport, TestClient and local HTTP remain usable. Real external HTTP needs
both --live-gemini and FRAUDLENS_TEST_LIVE=1; that does not bypass provider caps.
"""
import os
from pathlib import Path
import tempfile
import pytest


def pytest_addoption(parser):
    parser.addoption('--live-gemini', action='store_true', default=False,
                     help='Explicitly enable external HTTP tests; original provider controls still apply.')


def pytest_configure(config):
    if config.getoption('--live-gemini') and os.environ.get('FRAUDLENS_TEST_LIVE') == '1':
        return
    patch = pytest.MonkeyPatch()
    config._fraudlens_network_guard = patch
    patch.setenv('FRAUDLENS_TEST_LIVE', '0')
    config._fraudlens_test_controls = tempfile.TemporaryDirectory(prefix='fraudlens_pytest_controls_')
    # A mistakenly invoked adapter may reserve before reaching HTTP. Never let
    # that reservation or its rejected outcome touch an inherited pilot ledger.
    patch.setenv('FRAUDLENS_LIVE_LEDGER', '')
    patch.setenv('GEMINI_QUOTA_BUDGET',str(Path(config._fraudlens_test_controls.name)/'quota.json'))
    patch.setenv('GEMINI_QUOTA_CONSUMER','offline-test')
    patch.delenv('FRAUDLENS_RECOVERY_ID',raising=False)
    import httpx
    from urllib.parse import urlsplit
    local = {'localhost', '127.0.0.1', '::1'}
    def permitted(url):
        if urlsplit(str(url)).hostname not in local:
            raise AssertionError('External HTTP disabled in ordinary tests; use controlled transport fixtures.')
    original = httpx.HTTPTransport.handle_request
    original_async = httpx.AsyncHTTPTransport.handle_async_request
    def handle(self, request):
        permitted(request.url)
        return original(self, request)
    async def handle_async(self, request):
        permitted(request.url)
        return await original_async(self, request)
    patch.setattr(httpx.HTTPTransport, 'handle_request', handle)
    patch.setattr(httpx.AsyncHTTPTransport, 'handle_async_request', handle_async)
    import requests
    send = requests.adapters.HTTPAdapter.send
    def send_guard(self, request, **kwargs):
        permitted(request.url)
        return send(self, request, **kwargs)
    patch.setattr(requests.adapters.HTTPAdapter, 'send', send_guard)
    try:
        import aiohttp
    except ImportError:
        return
    create_connection = aiohttp.TCPConnector._create_connection
    async def connect_guard(self, request, *args, **kwargs):
        permitted(request.url)
        return await create_connection(self, request, *args, **kwargs)
    patch.setattr(aiohttp.TCPConnector, '_create_connection', connect_guard)


def pytest_unconfigure(config):
    patch = getattr(config, '_fraudlens_network_guard', None)
    if patch:
        patch.undo()
        config._fraudlens_test_controls.cleanup()
