"""Handlers for user-created tokens (``/auth/tokens``)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from aiohttp import web
from aiohttp_csrf import csrf_protect, generate_token
from aiohttp_jinja2 import template
from aiohttp_session import get_session
from wtforms import BooleanField, Form, HiddenField, SubmitField

from jwt_authorizer.handlers import routes
from jwt_authorizer.handlers.util import authenticated
from jwt_authorizer.session import Session, SessionHandle

if TYPE_CHECKING:
    from aioredis import Redis
    from jwt_authorizer.config import Config
    from jwt_authorizer.factory import ComponentFactory
    from jwt_authorizer.tokens import VerifiedToken
    from multidict import MultiDictProxy
    from typing import Dict, Optional, Union

__all__ = [
    "get_token_by_handle",
    "get_tokens",
    "get_tokens_new",
    "post_delete_token",
    "post_tokens_new",
]


class AlterTokenForm(Form):
    """Form for altering an existing user token."""

    method_ = HiddenField("method_")
    csrf = HiddenField("_csrf")


def api_capabilities_token_form(
    capabilities: Dict[str, str],
    data: Optional[MultiDictProxy[Union[str, bytes, web.FileField]]] = None,
) -> Form:
    """Dynamically generates a form with checkboxes for capabilities.

    Parameters
    ----------
    capabilities : Dict[`str`, `str`]
        A mapping of capability names to descriptions to include in the form.
    data : MultiDictProxy[Union[`str`, `bytes`, FileField]], optional
        The submitted form data, if any.

    Returns
    -------
    form : `wtforms.Form`
        The generated form.
    """

    class NewCapabilitiesToken(Form):
        """Stub form, to which fields will be dynamically added."""

        submit = SubmitField("Generate New Token")

    NewCapabilitiesToken.capability_names = list(capabilities)
    for capability, description in capabilities.items():
        field = BooleanField(label=capability, description=description)
        setattr(NewCapabilitiesToken, capability, field)
    return NewCapabilitiesToken(data)


@routes.get("/auth/tokens", name="tokens")
@template("tokens.html")
@authenticated
async def get_tokens(
    request: web.Request, token: VerifiedToken
) -> Dict[str, object]:
    """Displays all tokens for the current user.

    Parameters
    ----------
    request : `aiohttp.web.Request`
        The incoming request.

    Returns
    -------
    response : `aiohttp.web.Response`
        The response.
    """
    config: Config = request.config_dict["jwt_authorizer/config"]
    factory: ComponentFactory = request.config_dict["jwt_authorizer/factory"]

    session = await get_session(request)
    message = session.pop("message", None)
    session["csrf"] = await generate_token(request)

    token_store = factory.create_token_store(request)
    user_id = token.claims[config.uid_key]
    await token_store.expire_tokens(user_id)
    user_tokens = await token_store.get_tokens(user_id)
    forms = {}
    for user_token in user_tokens:
        form = AlterTokenForm()
        form.csrf.data = session["csrf"]
        forms[user_token.key] = form

    return {
        "message": message,
        "tokens": user_tokens,
        "forms": forms,
        "csrf_token": session["csrf"],
    }


@routes.get("/auth/tokens/new")
@template("new_token.html")
@authenticated
async def get_tokens_new(
    request: web.Request, token: VerifiedToken
) -> Dict[str, object]:
    """Return a form for creating a new token.

    Parameters
    ----------
    request : `aiohttp.web.Request`
        The incoming request.

    Returns
    -------
    response : `aiohttp.web.Response`
        The response.
    """
    config: Config = request.config_dict["jwt_authorizer/config"]

    form = api_capabilities_token_form(config.known_capabilities)

    session = await get_session(request)
    session["csrf"] = await generate_token(request)

    return {
        "form": form,
        "capabilities": config.known_capabilities,
        "csrf_token": session["csrf"],
    }


@routes.post("/auth/tokens/new")
@csrf_protect
@template("new_token.html")
@authenticated
async def post_tokens_new(
    request: web.Request, token: VerifiedToken
) -> Dict[str, object]:
    """Create a new token based on form parameters.

    Parameters
    ----------
    request : `aiohttp.web.Request`
        The incoming request, normally from nginx's ``auth_request``
        directive.

    Returns
    -------
    response : `aiohttp.web.Response`
        The response.
    """
    config: Config = request.config_dict["jwt_authorizer/config"]
    factory: ComponentFactory = request.config_dict["jwt_authorizer/factory"]
    redis: Redis = request.config_dict["jwt_authorizer/redis"]

    capabilities = config.known_capabilities
    form = api_capabilities_token_form(capabilities, await request.post())

    if not form.validate():
        return {"form": form, "capabilities": capabilities}

    handle = SessionHandle()

    new_capabilities = []
    for capability in capabilities:
        if form[capability].data:
            new_capabilities.append(capability)
    scope = " ".join(new_capabilities)
    claims: Dict[str, object] = {"scope": scope, "jti": handle.key}
    email = token.claims.get("email")
    if email:
        claims["email"] = email
    user = token.claims.get(config.username_key)
    if user:
        claims[config.username_key] = user
    uid = token.claims[config.uid_key]
    claims[config.uid_key] = uid

    # FIXME: Copies groups. Useful for WebDAV, maybe not necessary
    #
    # claims['isMemberOf'] = decoded_token['isMemberOf']

    issuer = factory.create_token_issuer()
    session_store = factory.create_session_store(request)
    token_store = factory.create_token_store(request)
    token = issuer.issue_token(claims)
    auth_session = Session.create(handle, token)
    pipeline = redis.pipeline()
    await session_store.store_session(auth_session, pipeline)
    token_store.store_session(uid, auth_session, pipeline)
    await pipeline.execute()

    message = (
        f"Your Newly Created Token. Keep these Secret!<br>\n"
        f"Token: {handle.encode()} <br>"
    )
    session = await get_session(request)
    session["message"] = message

    location = request.app.router["tokens"].url_for()
    raise web.HTTPFound(location)


@routes.get("/auth/tokens/{handle}")
@template("token.html")
@authenticated
async def get_token_by_handle(
    request: web.Request, token: VerifiedToken
) -> Dict[str, object]:
    """Displays information about a single token.

    Parameters
    ----------
    request : `aiohttp.web.Request`
        The incoming request.

    Returns
    -------
    response : `aiohttp.web.Response`
        The response.
    """
    config: Config = request.config_dict["jwt_authorizer/config"]
    factory: ComponentFactory = request.config_dict["jwt_authorizer/factory"]
    handle = request.match_info["handle"]

    token_store = factory.create_token_store(request)
    user_id = token.claims[config.uid_key]
    user_token = None
    for entry in await token_store.get_tokens(user_id):
        if entry.key == handle:
            user_token = entry
            break

    if not user_token:
        msg = f"No token with handle {handle} found"
        raise web.HTTPNotFound(reason=msg, text=msg)

    return {"token": user_token}


@routes.post("/auth/tokens/{handle}")
@csrf_protect
@authenticated
async def post_delete_token(
    request: web.Request, token: VerifiedToken
) -> web.Response:
    """Deletes a single token.

    Parameters
    ----------
    request : `aiohttp.web.Request`
        The incoming request.

    Returns
    -------
    response : Dict[`str`, `object`]
        Form variables that are processed by the template decorator, which
        turns them into an `aiohttp.web.Response`.
    """
    config: Config = request.config_dict["jwt_authorizer/config"]
    factory: ComponentFactory = request.config_dict["jwt_authorizer/factory"]
    redis: Redis = request.config_dict["jwt_authorizer/redis"]
    handle = request.match_info["handle"]

    form = AlterTokenForm(await request.post())
    if not form.validate() or form.method_.data != "DELETE":
        msg = "Invalid deletion request"
        raise web.HTTPForbidden(reason=msg, text=msg)

    token_store = factory.create_token_store(request)
    session_store = factory.create_session_store(request)
    pipeline = redis.pipeline()
    user_id = token.claims[config.uid_key]
    success = await token_store.revoke_token(user_id, handle, pipeline)
    if success:
        session_store.delete_session(handle, pipeline)
        await pipeline.execute()

    if success:
        message = f"Your token with the handle {handle} was deleted"
    else:
        message = "An error was encountered when deleting your token"
    session = await get_session(request)
    session["message"] = message

    location = request.app.router["tokens"].url_for()
    raise web.HTTPFound(location)
