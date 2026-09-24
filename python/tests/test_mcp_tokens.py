"""The checks an MCP server makes on an access token (chapter 13), one at a time.

RFC 9068 lists what a resource server must check in a JWT access token: its type, its issuer, its
audience, its signature and its expiry. Each test below hands the verifier a token that fails exactly
one of them and requires the refusal to say which, then one that passes them all.
"""

from __future__ import annotations

import time

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec

from mcp_governance.tokens import (
    ISSUER,
    PRIVATE_KEY,
    PUBLIC_KEY,
    LabIssuer,
    TokenRefused,
    Verifier,
    public_key_at,
)

HERE = "http://127.0.0.1:8765/mcp"
ELSEWHERE = "http://127.0.0.1:8766/mcp"


@pytest.fixture(scope="module")
def issuer() -> LabIssuer:
    return LabIssuer.generate()


@pytest.fixture(scope="module")
def verifier(issuer: LabIssuer) -> Verifier:
    return Verifier(issuer.public_key(), issuer=ISSUER, audience=HERE)


def token(issuer: LabIssuer, **changes: object) -> str:
    fields: dict = {"subject": "1", "audience": HERE, "scopes": ["tickets:read"], "client_id": "a-client"}
    fields.update(changes)
    return issuer.issue(**fields)


def refusal(verifier: Verifier, raw: str) -> str:
    with pytest.raises(TokenRefused) as refused:
        verifier.verify(raw)
    return refused.value.reason


def claims(**changes: object) -> dict:
    now = int(time.time())
    base = {"iss": ISSUER, "aud": HERE, "sub": "1", "client_id": "a-client", "scope": "", "iat": now}
    base.update({"exp": now + 300, "jti": "id-1", **changes})
    return base


def test_a_token_issued_for_this_server_says_who_which_client_and_what_it_allows(issuer, verifier):
    grant = verifier.verify(token(issuer, scopes=["kb:read", "tickets:read"]))
    assert (grant.subject, grant.client_id) == ("1", "a-client")
    assert grant.scopes == {"kb:read", "tickets:read"}
    assert grant.token_id


def test_a_token_issued_for_another_server_is_refused_however_valid_it_is_there(issuer, verifier):
    elsewhere = token(issuer, audience=ELSEWHERE)
    assert Verifier(issuer.public_key(), issuer=ISSUER, audience=ELSEWHERE).verify(elsewhere)
    assert refusal(verifier, elsewhere) == f"it was issued for {ELSEWHERE}, not for this server"


def test_an_upper_case_scheme_or_host_is_the_same_server(issuer, verifier):
    # The specification's canonical address is lower case, and it asks servers to accept upper case too.
    assert verifier.verify(token(issuer, audience="HTTP://127.0.0.1:8765/mcp/")).subject == "1"


def test_an_expired_token_is_refused(issuer, verifier):
    old = token(issuer, issued_at=int(time.time()) - 600, lifetime=300)
    assert refusal(verifier, old) == "it has expired"


def test_a_token_signed_with_another_key_is_refused_even_in_the_issuers_name(verifier):
    impostor = LabIssuer.generate()  # same name, different key
    assert impostor.name == ISSUER
    assert refusal(verifier, token(impostor)) == "its signature doesn't match the issuer's key"


def test_a_token_from_another_issuer_is_refused(verifier):
    other = LabIssuer.generate("https://other-issuer.invalid")
    # Checked against the other issuer's own key, so only the issuer is wrong.
    against_its_key = Verifier(other.public_key(), issuer=ISSUER, audience=HERE)
    assert (
        refusal(against_its_key, token(other))
        == f"it wasn't issued by {ISSUER}, the issuer this server trusts"
    )


def test_an_unsigned_token_is_refused(verifier):
    unsigned = jwt.encode(claims(), key=None, algorithm="none", headers={"typ": "at+jwt"})
    assert refusal(verifier, unsigned) == "it isn't signed with ES256, the only algorithm the issuer uses"


def test_a_signed_jwt_that_isnt_an_access_token_is_refused(verifier):
    key = ec.generate_private_key(ec.SECP256R1())
    id_token = jwt.encode(claims(), key, algorithm="ES256")  # typ JWT, as an ID token has
    assert refusal(verifier, id_token) == "its type is 'JWT', not at+jwt, so it isn't an access token"


def test_a_token_missing_a_claim_rfc_9068_requires_is_refused(issuer):
    key = ec.generate_private_key(ec.SECP256R1())
    no_client = claims()
    del no_client["client_id"]
    raw = jwt.encode(no_client, key, algorithm="ES256", headers={"typ": "at+jwt"})
    assert (
        refusal(Verifier(key.public_key(), issuer=ISSUER, audience=HERE), raw) == "it has no client_id claim"
    )


def test_something_that_isnt_a_jwt_is_refused(verifier):
    assert refusal(verifier, "not-a-token") == "it isn't a JWT"


def test_the_lab_issuer_keeps_its_key_and_a_server_reads_only_the_public_half(tmp_path):
    public = public_key_at(tmp_path)  # a server starting first makes the issuer, as its first use would
    assert (tmp_path / PRIVATE_KEY).exists() and (tmp_path / PUBLIC_KEY).exists()
    raw = LabIssuer.at(tmp_path).issue(subject="2", audience=HERE, scopes=[], client_id="c")
    assert Verifier(public, issuer=ISSUER, audience=HERE).verify(raw).subject == "2"
    assert b"PRIVATE" not in (tmp_path / PUBLIC_KEY).read_bytes()
