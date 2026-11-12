import importlib
import socket
import ssl
from unittest.mock import MagicMock

import pytest


@pytest.fixture
def proxy_module(monkeypatch):
    from pathlib import Path

    monkeypatch.syspath_prepend(str(Path(__file__).parents[2] / 'app/services'))
    return importlib.import_module('preview_registry_proxy')


def client_hello(host):
    outgoing = ssl.MemoryBIO()
    client = ssl.create_default_context().wrap_bio(ssl.MemoryBIO(), outgoing, server_hostname=host)
    with pytest.raises(ssl.SSLWantReadError):
        client.do_handshake()
    return outgoing.read()


@pytest.mark.parametrize('fragment_size', [1, 4, 17, 8192])
def test_connect_forwards_complete_client_hello_despite_socket_fragmentation(proxy_module, monkeypatch, fragment_size):
    m = proxy_module
    hello = client_hello('registry-1.docker.io')
    connection = MagicMock()
    connection.gettimeout.return_value = 10
    connection.recv.side_effect = [hello[index:index + fragment_size] for index in range(0, len(hello), fragment_size)] + [b'']
    upstream = MagicMock()
    upstream.__enter__.return_value = upstream
    monkeypatch.setattr(m.socket, 'getaddrinfo', lambda *_args, **_kwargs: [
        (socket.AF_INET, socket.SOCK_STREAM, 6, '', ('8.8.8.8', 443)),
    ])
    monkeypatch.setattr(m.socket, 'socket', lambda *_args: upstream)
    monkeypatch.setattr(m.select, 'select', lambda *_args: ([connection], [], []))
    handler = m.ProxyHandler.__new__(m.ProxyHandler)
    handler.path = 'registry-1.docker.io:443'
    handler.connection = connection
    handler.send_response = MagicMock()
    handler.end_headers = MagicMock()
    handler.do_CONNECT()
    upstream.sendall.assert_called_once_with(hello)
    handler.send_response.assert_called_once_with(200, 'Connection established')


@pytest.mark.parametrize('invalid', ['truncated', 'oversized', 'wrong-name'])
def test_connect_rejects_invalid_or_unapproved_tls_without_forwarding(proxy_module, monkeypatch, invalid):
    m = proxy_module
    hello = client_hello('example.invalid' if invalid == 'wrong-name' else 'registry-1.docker.io')
    if invalid == 'truncated':
        hello = hello[:12]
    elif invalid == 'oversized':
        hello = hello[:3] + (m.MAX_HELLO + 1).to_bytes(2) + hello[5:]
    connection = MagicMock()
    connection.gettimeout.return_value = 10
    connection.recv.side_effect = [hello, b'']
    upstream = MagicMock()
    upstream.__enter__.return_value = upstream
    monkeypatch.setattr(m.socket, 'getaddrinfo', lambda *_args, **_kwargs: [
        (socket.AF_INET, socket.SOCK_STREAM, 6, '', ('8.8.8.8', 443)),
    ])
    monkeypatch.setattr(m.socket, 'socket', lambda *_args: upstream)
    handler = m.ProxyHandler.__new__(m.ProxyHandler)
    handler.path = 'registry-1.docker.io:443'
    handler.connection = connection
    handler.send_response = MagicMock()
    handler.end_headers = MagicMock()
    handler.do_CONNECT()
    upstream.sendall.assert_not_called()


@pytest.mark.parametrize('error', [ConnectionRefusedError, TimeoutError])
def test_connect_tries_next_validated_public_address(proxy_module, monkeypatch, error):
    m = proxy_module
    first, second = MagicMock(), MagicMock()
    second.__enter__.return_value = second
    first.connect.side_effect = error('First public endpoint unavailable')
    addresses = [
        (socket.AF_INET6, socket.SOCK_STREAM, 6, '', ('2606:4700::1111', 443, 0, 0)),
        (socket.AF_INET, socket.SOCK_STREAM, 6, '', ('8.8.8.8', 443)),
    ]
    monkeypatch.setattr(m.socket, 'getaddrinfo', lambda *_args, **_kwargs: addresses)
    factory = MagicMock(side_effect=[first, second])
    monkeypatch.setattr(m.socket, 'socket', factory)
    hello = client_hello('registry-1.docker.io')
    connection = MagicMock()
    connection.gettimeout.return_value = 10
    connection.recv.side_effect = [hello, b'']
    monkeypatch.setattr(m.select, 'select', lambda *_args: ([connection], [], []))
    handler = m.ProxyHandler.__new__(m.ProxyHandler)
    handler.path = 'registry-1.docker.io:443'
    handler.connection = connection
    handler.send_response = MagicMock()
    handler.end_headers = MagicMock()
    handler.do_CONNECT()
    first.connect.assert_called_once_with(addresses[0][4])
    first.close.assert_called_once()
    second.connect.assert_called_once_with(addresses[1][4])
    second.sendall.assert_called_once_with(hello)
    assert [call.args[0] for call in factory.call_args_list] == [socket.AF_INET6, socket.AF_INET]


def test_public_address_fallback_shares_one_connection_deadline(proxy_module, monkeypatch):
    m = proxy_module
    first, second = MagicMock(), MagicMock()
    first.connect.side_effect = TimeoutError('First public endpoint timed out')
    factory = MagicMock(side_effect=[first, second])
    monkeypatch.setattr(m.socket, 'socket', factory)
    clock = iter([10, 10, 15])
    monkeypatch.setattr(m.time, 'monotonic', lambda: next(clock))
    addresses = [
        (socket.AF_INET, socket.SOCK_STREAM, 6, '', ('8.8.8.8', 443)),
        (socket.AF_INET, socket.SOCK_STREAM, 6, '', ('1.1.1.1', 443)),
    ]
    assert m.connect_registry(addresses) is second
    first.settimeout.assert_called_once_with(5)
    assert second.settimeout.call_args_list[0].args == (5,)
    first.close.assert_called_once()


def test_exhausted_connection_deadline_does_not_open_another_socket(proxy_module, monkeypatch):
    m = proxy_module
    connection = MagicMock()
    connection.connect.side_effect = TimeoutError('Connection deadline elapsed')
    factory = MagicMock(return_value=connection)
    monkeypatch.setattr(m.socket, 'socket', factory)
    clock = iter([10, 10, 20])
    monkeypatch.setattr(m.time, 'monotonic', lambda: next(clock))
    addresses = [
        (socket.AF_INET, socket.SOCK_STREAM, 6, '', ('8.8.8.8', 443)),
        (socket.AF_INET, socket.SOCK_STREAM, 6, '', ('1.1.1.1', 443)),
    ]
    with pytest.raises(OSError):
        m.connect_registry(addresses)
    factory.assert_called_once()
    connection.close.assert_called_once()


@pytest.mark.parametrize('private_address', ['127.0.0.1', '169.254.169.254', '::1'])
def test_fallback_rejects_entire_dns_answer_when_any_address_is_not_public(
    proxy_module, monkeypatch, private_address,
):
    m = proxy_module
    addresses = [
        (socket.AF_INET, socket.SOCK_STREAM, 6, '', ('8.8.8.8', 443)),
        (socket.AF_INET6 if ':' in private_address else socket.AF_INET,
         socket.SOCK_STREAM, 6, '', (private_address, 443)),
    ]
    monkeypatch.setattr(m.socket, 'getaddrinfo', lambda *_args, **_kwargs: addresses)
    factory = MagicMock()
    monkeypatch.setattr(m.socket, 'socket', factory)
    handler = m.ProxyHandler.__new__(m.ProxyHandler)
    handler.path = 'registry-1.docker.io:443'
    handler.send_error = MagicMock()
    handler.do_CONNECT()
    handler.send_error.assert_called_once_with(403)
    factory.assert_not_called()
