#!/usr/bin/env python
import asyncio
import argparse
import logging
import os
import sys
from urllib.parse import urlparse
from enum import Enum
from typing import Optional, Dict, List, Set, Any, Tuple
from datetime import datetime, timedelta

from wakeonlan import send_magic_packet
import ping3
import uvicorn
import yaml
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, validator
from starlette.responses import RedirectResponse


logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%d/%m/%Y %H:%M:%S'
)
log = logging.getLogger()


class Handlers:

    available = {}

    @staticmethod
    def register(key):
        def decorated(clazz):
            Handlers.available[key] = clazz
            return clazz
        return decorated


class Scheme(Enum):
    HTTP = "http"


class Match(BaseModel):
    route: str


class ProxyTarget(BaseModel):
    handler: str
    target_url: str
    methods: List[str] = ["GET", "POST"]
    matches: List[Match]
    options: Dict[str, str] = {}

    @validator('handler')
    def must_be_available(cls, value):
        if value not in Handlers.available:
            raise ValueError(f"Unknown handler '{value}', available: {list(Handlers.available.keys())}")
        return value


class Configuration(BaseModel):
    targets: List[ProxyTarget]


class BaseHandler:

    methods: List[str]
    kwargs: Dict[str, Any]
    required_keys = set()

    summary: str = "GENERIC HANDLER"
    description: str = "Generic base class, no implementation..."

    def __init__(self, methods, **kwargs) -> None:
        self.methods = methods
        missing = []
        for key in self.required_keys:
            if key not in kwargs:
                missing.append(key)
        if missing:
            raise ValueError(f"{self.__class__.__name__}: missing keys: {missing}")
        self.kwargs = kwargs

    @property
    def add_api_route_kwargs(self):
        return {
            "endpoint": self.route_handler,
            "description": self.description,
            "summary": self.summary,
            "methods": self.methods
        }

    async def _handler(self, **kwargs):
        raise NotImplemented

    async def route_handler(self, path_in=None):
        log.info(f"Incoming request with path: {path_in}")
        return await self._handler(path_in=path_in, **self.kwargs)


@Handlers.register("plain")
class PlainRedirect(BaseHandler):

    summary = "PLAIN REDIRECT"
    description = "A simple redirect"
    required_keys = {"target_url"}

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.description = f"{self.description} to <b>{self.kwargs.get('target_url')}</b>"

    async def _handler(self, target_url, path_in=None):
        redirect_target = os.path.join(target_url, path_in)
        log.info(f"Redirecting to '{redirect_target}'")
        return RedirectResponse(redirect_target)


@Handlers.register("wol")
class WolRedirect(PlainRedirect):

    summary = "Wake-on-LAN"
    description = """
A simple WoL redirect. It tries to ping the target url before redirecting.
If it's not responding, it sends a magic packet to the target machine
, and then again waits for the host to become reachable.
"""
    required_keys = {"target_url", "mac"}

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.description = f"Redirects to <b>{self.kwargs.get('target_url')}</b>\n{WolRedirect.description}"

    async def _handler(self, target_url=None, mac=None, timeout_s=10, **kwargs):
        async def ping_until(timeout: int):
            start = datetime.now()
            while not (rtt := ping3.ping(host)):
                log.debug(f"'{host}' ping failed, retrying in 1s")
                if datetime.now() - start > timedelta(seconds=timeout):
                    raise TimeoutError
                await asyncio.sleep(1)
            return rtt

        timeout_s = int(timeout_s)
        host = str(urlparse(target_url).hostname)
        try:
            log.debug(f"Pinging '{host}' with timeout {timeout_s}s")
            first_ping = ping3.ping(host, unit="ms", timeout=timeout_s)
            if first_ping:
                log.info(f"'{host}' ping successful in {first_ping}ms")
            else:
                send_magic_packet(mac)
                last_ping = ping_until(timeout_s)
                log.info(f"Host '{host}' woke up, rtt={last_ping}")
        except (ping3.errors.PingError, TimeoutError) as e:
            log.error("Ping failed", e)
            raise HTTPException(status_code=504, detail=f"Ping failed: {e}")

        return await super()._handler(target_url, **kwargs)


def set_default_paths(app: FastAPI):

    @app.get("/")
    async def root() -> RedirectResponse:
        return RedirectResponse("/docs")

    return app


def create_app(configuration: Configuration = None):
    if not configuration:
        with open(os.environ.get("WOL-PROXY-CONFIG", "./config.yaml"), "r") as config:
            configuration = Configuration(**yaml.safe_load(config))

    app = FastAPI()
    set_default_paths(app)
    for target in configuration.targets:
        for match in target.matches:
            target_cfg = target.dict()
            target_cfg.pop("matches")
            options = target_cfg.pop("options")
            for k, v in options.items():
                target_cfg[k] = v
            handler_name = target_cfg.pop("handler")

            if match.route.endswith("/*"):
                match.route = match.route.replace("/*", "/{path_in:path}")

            handler: BaseHandler = Handlers.available[handler_name](**target_cfg)
            app.add_api_route(match.route, **handler.add_api_route_kwargs)

    return app


if __name__ == '__main__':

    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8080)
    args = parser.parse_args()

    uvicorn.run(create_app(), host=args.host, port=args.port)
