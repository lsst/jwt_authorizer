"""Handler for /.well-known/jwks.json."""

from __future__ import annotations

from typing import TYPE_CHECKING

from aiohttp import web

from gafaelfawr.handlers import routes

if TYPE_CHECKING:
    from gafaelfawr.config import Config
    from structlog import BoundLogger

__all__ = ["get_well_known_jwks"]


@routes.get("/.well-known/jwks.json")
async def get_well_known_jwks(request: web.Request) -> web.Response:
    """Handler for /.well-known/jwks.json.

    Serve metadata about our signing key.

    Parameters
    ----------
    request : `aiohttp.web.Request`
        The incoming request.

    Returns
    -------
    response : `aiohttp.web.Response`
        The outgoing response.
    """
    config: Config = request.config_dict["gafaelfawr/config"]
    logger: BoundLogger = request["safir/logger"]

    jwks = config.issuer.keypair.public_key_as_jwks(kid=config.issuer.kid)
    logger.info("Returned JWKS")
    return web.json_response({"keys": [jwks]})
