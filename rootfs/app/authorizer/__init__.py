# This file is part of jwt_authorizer.
#
# Developed for the LSST Data Management System.
# This product includes software developed by the LSST Project
# (https://www.lsst.org).
# See the COPYRIGHT file at the top-level directory of this distribution
# for details of code ownership.
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.


import base64
import logging
from datetime import datetime, timedelta
from typing import Optional, Any, Dict, Mapping, Tuple

import jwt
from flask import request, Response, current_app, render_template, flash, redirect, url_for
from jwt import PyJWTError

from .authnz import authenticate, authorize, verify_authorization_strategy
from .config import Config, AuthorizerApp
from .token import (
    issue_token,
    api_capabilities_token_form,
    new_oauth2_proxy_ticket,
    new_oauth2_proxy_handle,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = AuthorizerApp(__name__)


ORIGINAL_TOKEN_HEADER = "X-Orig-Authorization"


@app.route("/auth")
def authnz_token():  # type: ignore
    """
    Authenticate and authorize a token.
    :query capability: one or more capabilities to check.
    :query satisfy: satisfy ``all`` (default) or ``any`` of the
    capability checks.
    :query reissue_token: if ``true``, then reissue token before
    setting the user headers.
    :>header Authorization: The token should be in this header as
    type ``Bearer``, but it may be type ``Basic`` if ``x-oauth-basic``
    is the username or password.
    :<header X-Auth-Request-Email: If enabled and email is available,
    this will be set based on the ``email`` claim.
    :<header X-Auth-Request-User: If enabled and the field is available,
    this will be set from token based on the ``JWT_USERNAME_KEY`` field
    :<header X-Auth-Request-Uid: If enabled and the field is available,
    this will be set from token based on the ``JWT_UID_KEY`` field
    :<header X-Auth-Request-Token: If enabled, the encoded token will
    be set. If ``reissue_token`` is true, the token is reissued first
    :<header WWW-Authenticate: If the request is unauthenticated, this
    header will be set.
    """
    # Default to Server Error for safety, so we must always set it to 200
    # if it's okay.
    response = Response(status=500)
    if "Authorization" not in request.headers:
        _make_needs_authentication(response, "No Authorization header", "")
        return response

    encoded_token = _find_token("Authorization")
    if not encoded_token:
        _make_needs_authentication(response, "Unable to find token", "")
        return response

    # Authentication
    try:
        verified_token = authenticate(encoded_token)
    except PyJWTError as e:
        # All JWT failures get 401s and are logged.
        _make_needs_authentication(response, "Invalid Token", str(e))
        logger.exception("Failed to authenticate Token")
        logger.exception(e)
        return response

    # Authorization
    success, message = authorize(verified_token)

    # Add info about authorization whether or not authorization succeeded
    _make_capability_headers(response, encoded_token)

    jti = verified_token.get("jti", "UNKNOWN")
    if success:
        response.status_code = 200
        _make_success_headers(response, encoded_token)
        logger.info(f"Allowed token with Token ID: {jti} " f"from issuer {verified_token['iss']}")
        return response

    response.set_data(message)
    # All authorization failures get 403s
    response.status_code = 403
    logger.error(f"Failed to authorize Token ID {jti} because {message}")
    return response


@app.route("/auth/tokens/new", methods=["GET", "POST"])
def new_tokens():  # type: ignore
    try:
        encoded_token = request.headers["X-Auth-Request-Token"]
        decoded_token = authenticate(encoded_token)
    except PyJWTError as e:
        response = Response()
        _make_needs_authentication(response, "Invalid Token", str(e))
        logger.exception("Failed to authenticate Token")
        logger.exception(e)
        return response

    capabilities = current_app.config["KNOWN_CAPABILITIES"]
    form = api_capabilities_token_form(capabilities)

    if request.method == "POST" and form.validate():
        new_capabilities = []
        for capability in capabilities:
            if form[capability].data:
                new_capabilities.append(capability)
        scope = " ".join(new_capabilities)
        aud = current_app.config.get("OAUTH2_JWT.AUD.DEFAULT", decoded_token["aud"])
        new_token: Dict[str, Any] = {"scope": scope, "aud": aud}
        email = decoded_token.get("email")
        user = decoded_token.get(current_app.config["JWT_USERNAME_KEY"])
        uid = decoded_token.get(current_app.config["JWT_UID_KEY"])
        if email:
            new_token["email"] = email
        if user:
            new_token[current_app.config["JWT_USERNAME_KEY"]] = user
        if uid:
            new_token[current_app.config["JWT_UID_KEY"]] = uid

        # FIXME: Copies groups. Useful for WebDAV, maybe not necessary
        #
        # new_token['isMemberOf'] = decoded_token['isMemberOf']

        ticket_handle = new_oauth2_proxy_handle()
        new_token["jti"] = ticket_handle

        exp = datetime.utcnow() + timedelta(seconds=current_app.config["OAUTH2_JWT_EXP"])
        oauth2_proxy_ticket = new_oauth2_proxy_ticket(ticket_handle)
        _ = issue_token(
            new_token, exp=exp, store_user_info=True, oauth2_proxy_ticket=oauth2_proxy_ticket
        )

        flash(
            f"Your Newly Created Token. Keep these Secret!<br>\n"
            f"Token: {oauth2_proxy_ticket} <br>"
        )
        return redirect(url_for("new_tokens"))

    return render_template(
        "new_token.html", title="New Token", form=form, capabilities=capabilities
    )


def _make_capability_headers(response: Response, encoded_token: str) -> None:
    """Set Headers scope headers that can be returned in the case of
    API authorization failure due to required capabiliites.
    :return: The mutated response object.
    """
    decoded_token = jwt.decode(encoded_token, verify=False)
    capabilities, satisfy = verify_authorization_strategy()
    response.headers["X-Auth-Request-Token-Capabilities"] = decoded_token.get("scope", "")
    response.headers["X-Auth-Request-Capabilities-Accepted"] = " ".join(capabilities)
    response.headers["X-Auth-Request-Capabilities-Satisfy"] = satisfy


def _make_success_headers(response: Response, encoded_token: str) -> None:
    """Set Headers that will be returned in a successful response.
    :return: The mutated response object.
    """
    _make_capability_headers(response, encoded_token)

    decoded_token = jwt.decode(encoded_token, verify=False)
    if current_app.config["SET_USER_HEADERS"]:
        email = decoded_token.get("email")
        user = decoded_token.get(current_app.config["JWT_USERNAME_KEY"])
        uid = decoded_token.get(current_app.config["JWT_UID_KEY"])
        groups_list = decoded_token.get("isMemberOf", list())
        if email:
            response.headers["X-Auth-Request-Email"] = email
        if user:
            response.headers["X-Auth-Request-User"] = user
        if uid:
            response.headers["X-Auth-Request-Uid"] = uid
        if groups_list:
            groups = ",".join([g["name"] for g in groups_list])
            response.headers["X-Auth-Request-Groups"] = groups

    ticket_prefix = current_app.config["OAUTH2_STORE_SESSION"]["TICKET_PREFIX"]
    original_auth = _find_token(ORIGINAL_TOKEN_HEADER) or ""
    oauth2_proxy_ticket = original_auth if original_auth.startswith(f"{ticket_prefix}:") else ""
    reissue_requested = request.args.get("reissue_token", "").lower() == "true"
    if reissue_requested:
        encoded_token, oauth2_proxy_ticket = _check_reissue_token(encoded_token, decoded_token)
    response.headers["X-Auth-Request-Token"] = encoded_token
    response.headers["X-Auth-Request-Token-Ticket"] = oauth2_proxy_ticket


def _check_reissue_token(encoded_token: str, decoded_token: Mapping[str, Any]) -> Tuple[str, str]:
    """
    Reissue the token under two scenarios.
    The first scenario is a newly logged in session with a cookie,
    indicated by the token being issued from another issuer.
    We reissue the token with a default audience.
    The second scenario is a request to an internal resource, as
    indicated by the `audience` parameter being equal to the
    configured internal audience, where the current token's audience
    is from the default audience.
    :param encoded_token: The current token, encoded
    :param decoded_token: The current token, decoded
    :return: An encoded token, which may have been reissued.
    """
    # Only reissue token if it's requested and if it's a different issuer than
    # this application uses to reissue a token
    iss = current_app.config.get("OAUTH2_JWT.ISS", "")
    assert len(iss), "ERROR: Reissue requested but no Issuer Configured"
    default_audience = current_app.config.get("OAUTH2_JWT.AUD.DEFAULT", "")
    internal_audience = current_app.config.get("OAUTH2_JWT.AUD.INTERNAL", "")
    to_internal_audience = request.args.get("audience") == internal_audience
    from_this_issuer = decoded_token["iss"] == iss
    from_default_audience = decoded_token["aud"] == default_audience
    oauth2_proxy_ticket = request.cookies.get("_oauth2_proxy", "")

    if not from_this_issuer:
        payload = dict(decoded_token)
        # These are inherently new sessions
        # This should happen only once, after initial login.
        # We transform the external provider tokens to internal tokens
        # with a fixed lifetime
        assert len(oauth2_proxy_ticket), "ERROR: OAuth2 Proxy ticket must exist"
        # If we are here, we haven't reissued a token and we're using Cookies
        # Since we already had a ticket, use token handle as `jti`
        previous_jti = decoded_token.get("jti", "")
        previous_iss = decoded_token["iss"]
        previous_aud = decoded_token["aud"]
        logger.debug(f"Exchanging from iss={previous_iss}, aud={previous_aud}, jti={previous_jti}")
        payload["jti"] = oauth2_proxy_ticket.split(".")[0]
        payload["aud"] = default_audience
        actor_claim = {
            "aud": previous_aud,
            "iss": previous_iss,
        }
        if previous_jti:
            actor_claim["jti"] = previous_jti
        payload["act"] = actor_claim
        exp = datetime.utcnow() + timedelta(seconds=current_app.config["OAUTH2_JWT_EXP"])
        encoded_token = issue_token(
            decoded_token, exp=exp, store_user_info=False, oauth2_proxy_ticket=oauth2_proxy_ticket
        )
    elif from_this_issuer and from_default_audience and to_internal_audience:
        payload = dict(decoded_token)
        # Requests to Internal Audiences
        # We should always have a `jti`
        ticket_handle = new_oauth2_proxy_handle()
        oauth2_proxy_ticket = new_oauth2_proxy_ticket(ticket_handle)
        previous_jti = decoded_token.get("jti", "")
        previous_iss = decoded_token["iss"]
        previous_aud = decoded_token["aud"]
        logger.debug(f"Exchanging from iss={previous_iss}, aud={previous_aud}, jti={previous_jti}")
        payload["jti"] = ticket_handle
        payload["aud"] = internal_audience
        # Store previous token information
        actor_claim = {
            "aud": previous_aud,
            "iss": previous_iss,
        }
        if previous_jti:
            actor_claim["jti"] = previous_jti
        if "act" in decoded_token:
            actor_claim["act"] = decoded_token["act"]
        payload["act"] = actor_claim
        exp = datetime.utcnow() + timedelta(seconds=current_app.config["OAUTH2_JWT_EXP"])
        # Note: Internal audiences should not need the ticket
        encoded_token = issue_token(
            payload, exp=exp, store_user_info=False, oauth2_proxy_ticket=oauth2_proxy_ticket
        )

    return encoded_token, oauth2_proxy_ticket


def _find_token(header: str) -> Optional[str]:
    """
    From the request, find the token we need. Normally it should
    be in the Authorization header of type ``Bearer``, but it may
    be of type Basic for clients that don't support OAuth.
    :type header: HTTP Header to check for token
    :return: The token text, if found, otherwise None.
    """
    header_value = request.headers.get(header, "")
    if not header_value or " " not in header_value:
        return None
    auth_type, auth_blob = header_value.split(" ")
    encoded_token = None
    if auth_type.lower() == "bearer":
        encoded_token = auth_blob
    elif "x-forwarded-access-token" in request.headers:
        encoded_token = request.headers["x-forwarded-access-token"]
    elif "x-forwarded-id-token" in request.headers:
        encoded_token = request.headers["x-forwarded-id-token"]
    elif auth_type.lower() == "basic":
        logger.debug("Using OAuth with Basic")
        # We fallback to user:token. We ignore the user.
        # The Token is in the password
        encoded_basic_auth = auth_blob
        basic_auth = base64.b64decode(encoded_basic_auth)
        user, password = basic_auth.strip().split(b":")
        if password == "x-oauth-basic":
            # Recommended default
            encoded_token = user.decode()
        elif user == "x-oauth-basic":
            # ... Could be this though
            encoded_token = password.decode()
        else:
            logger.info("No protocol for token specified")
            encoded_token = user.decode()
    return encoded_token


def _make_needs_authentication(response: Response, error: str, message: str) -> None:
    """Modify response for a 401 as appropriate"""
    response.status_code = 401
    response.set_data(error)
    if not current_app.config.get("WWW_AUTHENTICATE"):
        return
    realm = current_app.config["REALM"]
    if current_app.config["WWW_AUTHENTICATE"].lower() == "basic":
        # Otherwise, send Bearer
        response.headers["WWW-Authenticate"] = f'Basic realm="{realm}"'
    else:
        response.headers[
            "WWW-Authenticate"
        ] = f'Bearer realm="{realm}",error="{error}",error_description="{message}"'


def configure(settings_path: Optional[str] = None) -> None:
    settings_path = settings_path or "/etc/jwt-authorizer/authorizer.yaml"
    Config.validate(app, settings_path)


configure()
