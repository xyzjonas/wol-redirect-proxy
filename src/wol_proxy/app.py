#!/usr/bin/env python
import argparse
import asyncio
import logging
import os
import sys
from datetime import datetime, timedelta
from typing import Dict, List
from urllib.parse import urlparse

import ping3
import uvicorn
import yaml
from fastapi import FastAPI
from pydantic import BaseModel, validator, AnyHttpUrl
from starlette.requests import Request
from starlette.responses import RedirectResponse, Response, JSONResponse
from wakeonlan import send_magic_packet


FORMAT = "%(asctime)s %(levelname)s: %(message)s"
logging.basicConfig(
    level="NOTSET", format=FORMAT, datefmt="[%X]"
)
logger = logging.getLogger("wol")


class WolProxyError(Exception):
    message: str

    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)


class HostUnreachableError(WolProxyError):
    pass


class NoHandlerError(WolProxyError):
    pass


class Handlers:
    """All available handlers can be accessed through here."""

    available: Dict[str, type['BaseHandler']] = {}

    @staticmethod
    def register(key):
        def decorated(clazz):
            Handlers.available[key] = clazz
            return clazz
        return decorated


class ProxyMappingItem(BaseModel):
    """Model for a single redirect definition (configuration)."""
    source_url: AnyHttpUrl
    target_url: AnyHttpUrl
    handler: str
    methods: List[str] = ["GET", "POST"]
    options: Dict[str, str] = {}

    @validator('handler')
    def must_be_available(cls, value):
        if value not in Handlers.available:
            raise ValueError(
                f"Unknown handler '{value}', available: {list(Handlers.available.keys())}")
        return value


class Configuration(BaseModel):
    """The entire configuration structure."""
    targets: List[ProxyMappingItem]


class BaseHandler:

    target: ProxyMappingItem
    required_keys = set()

    summary: str = "GENERIC HANDLER"
    description: str = "Generic base class, no implementation."

    def __init__(self, target: ProxyMappingItem) -> None:
        self.target = target

        missing = [key for key in self.required_keys if key not in self.target.options]
        if missing:
            raise ValueError(f"{self.__class__.__name__}: missing keys: {missing}")

    async def _handler(self, request: Request, target_url: str, path_in=None):
        raise NotImplemented

    async def route_handler(self, request: Request, path_in=None):
        return await self._handler(request, target_url=self.target.target_url, path_in=path_in)


@Handlers.register("plain")
class PlainRedirect(BaseHandler):

    summary = "PLAIN REDIRECT"
    description = "A simple redirect."

    def __init__(self, target: ProxyMappingItem) -> None:
        super().__init__(target)
        self.description = f"{self.description}"

    async def _handler(self, request: Request, target_url: str, path_in=None):
        redirect_target = os.path.join(target_url, path_in or '')
        logger.info(f"Redirecting {request.method} to '{redirect_target}'")
        return RedirectResponse(redirect_target)


@Handlers.register("wol")
class WolRedirect(PlainRedirect):

    summary = "Wake-on-LAN"
    description = """A simple WoL redirect. It tries to ping the target url before redirecting.
If it's not responding, it sends a magic packet to the target machine 
and then again waits for the host to become reachable.
"""
    required_keys = {"mac", "timeout_s"}

    def __init__(self, target: ProxyMappingItem) -> None:
        super().__init__(target)

    async def _handler(self, request: Request, target_url: str, path_in=None):
        async def ping_until(timeout: int):
            start = datetime.now()
            while not (rtt := ping3.ping(host)):
                logger.debug(f"'{host}' ping failed, retrying in 1s")
                if datetime.now() - start > timedelta(seconds=timeout):
                    raise HostUnreachableError(f"Timeout: failed to reach {host!r} after {timeout}s")
                await asyncio.sleep(1)
            return rtt

        timeout_s = int(self.target.options.get("timeout_s"))
        host = str(urlparse(target_url).hostname)
        logger.debug(f"Pinging '{host}' with timeout {timeout_s}s")
        first_ping = ping3.ping(host, unit="ms", timeout=timeout_s)
        if first_ping:
            logger.info(f"'{host}' ping successful in {first_ping}ms")
        else:
            logger.info(f"Sending magic packet to {self.target.options['mac']}")
            send_magic_packet(self.target.options["mac"])
            logger.info(f"Waiting for '{host}' to come alive timeout={timeout_s}s")
            last_ping = await ping_until(timeout_s)
            logger.info(f"Host '{host}' woke up, rtt={last_ping}")

        return await super()._handler(request, target_url, path_in)


def generate_main_route_handler_with_options(handlers: list[BaseHandler]):
    """Merge handlers that share common path in a common handler function."""

    async def handler(request: Request, path_in=None) -> Response:
        """This is the actual FastAPI route handler."""
        hostname = request.base_url.hostname
        logger.info(f"Incoming request {hostname!r} with path: {path_in!r}")
        for h in handlers:
            if h.target.source_url.host == hostname:
                logger.info(f"Matched handler: {h.target.source_url} -> {h.target.target_url}")
                return await h.route_handler(request, path_in)

        logger.error(f"No matching handlers for: {request.base_url}")
        raise NoHandlerError(f"No matching handlers for: {request.base_url}")

    all_methods = list({method for handler in handlers for method in handler.target.methods})
    desc_list = '\n'.join([
        f'<li><b>{h.summary}</b>: [ {h.target.source_url} ] ➡ [ {h.target.target_url} ]</li>'
        for h in handlers
    ])
    return {
        "endpoint": handler,
        "summary": f"{len(handlers)} handler(s)",
        "methods": all_methods,
        "description": f"""
        <ol>
        {desc_list}
        </ol>
        """
    }


def read_configuration(config_path=None):
    if not config_path:
        config_path = os.environ.get("WOL-PROXY-CONFIG", None)
    if not config_path:
        home_dir = os.environ.get("HOME")
        config_path = os.environ.get("WOL-PROXY-CONFIG", os.path.join(home_dir, ".config/wol-redirect-proxy.yaml"))

    if not os.path.isfile(config_path):
        logger.critical(f"(!) Not a file {config_path!r}")
        sys.exit(1)

    logger.info(f"Reading configuration file {config_path!r}")
    with open(config_path, "r") as config:
        return Configuration(**yaml.safe_load(config))


def create_app(configuration: Configuration):
    app = FastAPI()

    handlers_by_path = {}

    for target in configuration.targets:
        path = target.source_url.path
        if path.endswith("/*"):
            path = path.replace("/*", "/{path_in:path}")

        handler: BaseHandler = Handlers.available[target.handler](target)
        if path not in handlers_by_path:
            handlers_by_path[path] = []
        handlers_by_path[path].append(handler)

    for path, handlers in sorted(handlers_by_path.items()):
        app.add_api_route(path, **generate_main_route_handler_with_options(handlers))

    return app


def get_error_handler(exception_type: type[WolProxyError]):
    status_code = 500
    if exception_type == HostUnreachableError:
        status_code = 504
    if exception_type == NoHandlerError:
        status_code = 404

    def error_handler(request: Request, exc: WolProxyError):
        logger.error(exc.message)
        return JSONResponse(
            status_code=status_code,
            content={"message": exc.message},
            headers={"Content-Type": "application/json"}
        )

    return error_handler


def main():
    parser = argparse.ArgumentParser(description="Start a simple WoL redirect proxy server.")
    parser.add_argument("--host", default="0.0.0.0", help="accept connections only to this address")
    parser.add_argument("--port", type=int, default=8080, help="start server listening on this port")
    parser.add_argument("--log-level", type=str, default="INFO", help="logging level (default=INFO)")
    parser.add_argument("-c", metavar="CONFIG", dest="configuration", type=str, required=False, help="non-default configuration location")
    parser.add_argument("--list", action="store_true", help="list available handler types")
    args = parser.parse_args()

    if args.list:
        print("Available handlers:")
        print("-" * 25)
        for handler_name, handler_cls in Handlers.available.items():
            print("> " + handler_name)
            print(handler_cls.summary)
            print(handler_cls.description)
            if handler_cls.required_keys:
                print("required options:")
                for opt in handler_cls.required_keys:
                    print("- " + opt)
            print("-" * 25)
        sys.exit(0)

    logger.setLevel(args.log_level)
    logger.info(f"""Starting...
▀██ ▀██▀  ▀█▀         ▀██        ▀██▀▀█▄                                    
 ▀█▄ ▀█▄  ▄▀    ▄▄▄    ██         ██   ██ ▄▄▄ ▄▄    ▄▄▄   ▄▄▄ ▄▄▄  ▄▄▄▄ ▄▄▄ 
  ██  ██  █   ▄█  ▀█▄  ██         ██▄▄▄█▀  ██▀ ▀▀ ▄█  ▀█▄  ▀█▄▄▀    ▀█▄  █  
   ███ ███    ██   ██  ██         ██       ██     ██   ██   ▄█▄      ▀█▄█   
    █   █      ▀█▄▄█▀ ▄██▄       ▄██▄     ▄██▄     ▀█▄▄█▀ ▄█  ██▄     ▀█    
                                                                   ▄▄ █     
                                                                    ▀▀
See http://{args.host}:{args.port}/docs to see the configured routes.
----------------------------------------------------------------------------
    """)
    configuration = read_configuration(args.configuration)

    app = create_app(configuration)
    app.add_exception_handler(WolProxyError, get_error_handler(WolProxyError))
    app.add_exception_handler(HostUnreachableError, get_error_handler(HostUnreachableError))
    app.add_exception_handler(NoHandlerError, get_error_handler(NoHandlerError))

    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == '__main__':
    main()
