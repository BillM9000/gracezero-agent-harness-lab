"""Access tokens for MCP servers over HTTP (chapter 13): the checks a server makes, and a test issuer.

A protected MCP server is an OAuth 2.1 resource server. It serves a request only with an access token
that the authorization server it trusts issued for it, for one person, with scopes. The tokens here
follow RFC 9068, the JSON Web Token (JWT) profile for OAuth 2.0 access tokens: signed JSON whose
claims name the issuer (iss), the server it's for (aud), the person (sub), the client application
(client_id), the scopes (scope), when it was issued and expires (iat, exp) and its own id (jti).

- Verifier is what the server runs on every request: the checks RFC 9068 lists for a resource
  server, each failure a reason the server sends back with its 401.
- LabIssuer stands in for the authorization server. It signs tokens with a key on your disk for
  whoever it's asked to. A real authorization server signs only after the person has signed in, and
  publishes its public key for servers to fetch; the lab has none, so nothing here checks who anyone
  is. Use it for the lab's steps and tests, never for anything real.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

# The lab's test issuer names itself with an address nothing answers at: it's code, not a service.
ISSUER = "https://test-issuer.invalid"
ALGORITHM = "ES256"  # the one algorithm the issuer signs with, and so the only one a server accepts
LIFETIME = 300  # seconds: the specification asks authorization servers for short-lived tokens
# Every claim RFC 9068 requires in an access token.
REQUIRED = ["iss", "aud", "sub", "client_id", "iat", "exp", "jti"]
TOKEN_TYPES = ("at+jwt", "application/at+jwt")
PRIVATE_KEY = "issuer-key.pem"
PUBLIC_KEY = "issuer-public.pem"


def canonical(uri: str) -> str:
    """A server's address in the specification's canonical form: scheme and host in lower case, and
    no trailing slash. The specification asks servers to accept upper-case schemes and hosts too."""
    parts = urlsplit(uri)
    path = parts.path.rstrip("/")
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), path, parts.query, parts.fragment))


@dataclass(frozen=True)
class Grant:
    """What a verified token says: who it's for, which client presented it, and what it allows."""

    subject: str  # the person, as the issuer identifies them
    client_id: str  # the application acting for them
    scopes: frozenset[str]
    token_id: str  # jti: ties an audit record to a token without keeping the token


class TokenRefused(Exception):
    """A token the server won't accept. The reason is written to go back in a 401's challenge, so it
    says what was wrong, in plain ASCII without quotation marks, and never repeats the token."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class Verifier:
    """The checks an MCP server makes on every access token, for one server and one issuer."""

    def __init__(self, public_key: ec.EllipticCurvePublicKey, *, issuer: str, audience: str) -> None:
        self.key = public_key
        self.issuer = issuer
        self.audience = canonical(audience)  # this server's own address, and the only audience it accepts

    def verify(self, token: str) -> Grant:
        """RFC 9068's checks for a JWT access token: its type, signature, issuer, expiry and audience."""
        try:
            header = jwt.get_unverified_header(token)
        except jwt.InvalidTokenError:
            raise TokenRefused("it isn't a JWT") from None
        # The type: an access token, not another kind of signed JWT, such as an ID token, passed off as one.
        if str(header.get("typ", "")).lower() not in TOKEN_TYPES:
            raise TokenRefused(f"its type is {header.get('typ')!r}, not at+jwt, so it isn't an access token")
        try:
            # The signature, with the issuer's one algorithm ("none" is never accepted); then the issuer,
            # the expiry, and every claim RFC 9068 requires. The audience is checked below, on its own.
            claims = jwt.decode(
                token,
                self.key,
                algorithms=[ALGORITHM],
                issuer=self.issuer,
                options={"require": REQUIRED, "verify_aud": False},
            )
        except jwt.InvalidAlgorithmError:
            raise TokenRefused(
                f"it isn't signed with {ALGORITHM}, the only algorithm the issuer uses"
            ) from None
        except jwt.InvalidSignatureError:
            raise TokenRefused("its signature doesn't match the issuer's key") from None
        except jwt.ExpiredSignatureError:
            raise TokenRefused("it has expired") from None
        except jwt.InvalidIssuerError:
            raise TokenRefused(f"it wasn't issued by {self.issuer}, the issuer this server trusts") from None
        except jwt.MissingRequiredClaimError as e:
            raise TokenRefused(f"it has no {e.claim} claim") from None
        except jwt.InvalidTokenError as e:
            raise TokenRefused(f"it isn't valid: {e}") from None
        # The audience: this server, and only this server. A token issued for any other service is
        # refused however valid it is there, so a token can't be carried from one server to another.
        audiences = claims["aud"] if isinstance(claims["aud"], list) else [claims["aud"]]
        if self.audience not in [canonical(str(a)) for a in audiences]:
            raise TokenRefused(f"it was issued for {' '.join(map(str, audiences))}, not for this server")
        return Grant(
            subject=str(claims["sub"]),
            client_id=str(claims["client_id"]),
            scopes=frozenset(str(claims.get("scope", "")).split()),
            token_id=str(claims["jti"]),
        )


class LabIssuer:
    """A stand-in for an authorization server: it signs any token it's asked for. Tests and the
    book's steps only."""

    def __init__(self, key: ec.EllipticCurvePrivateKey, name: str = ISSUER) -> None:
        self._key = key
        self.name = name

    @classmethod
    def generate(cls, name: str = ISSUER) -> LabIssuer:
        """A new issuer with a key that exists only in memory."""
        return cls(ec.generate_private_key(ec.SECP256R1()), name)

    @classmethod
    def at(cls, folder: Path) -> LabIssuer:
        """The lab's issuer, whose key is kept in folder, made on first use."""
        private = folder / PRIVATE_KEY
        if not private.exists():
            folder.mkdir(parents=True, exist_ok=True)
            key = ec.generate_private_key(ec.SECP256R1())
            pem = key.private_bytes(
                serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
            )
            private.write_bytes(pem)
        key = serialization.load_pem_private_key(private.read_bytes(), password=None)
        assert isinstance(key, ec.EllipticCurvePrivateKey)
        issuer = cls(key)
        public = folder / PUBLIC_KEY
        if not public.exists():
            public.write_bytes(
                issuer.public_key().public_bytes(
                    serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
                )
            )
        return issuer

    def public_key(self) -> ec.EllipticCurvePublicKey:
        return self._key.public_key()

    def issue(
        self,
        *,
        subject: str,
        audience: str,
        scopes: Iterable[str],
        client_id: str,
        lifetime: int = LIFETIME,
        issued_at: int | None = None,
    ) -> str:
        """A signed access token for one person, one client and one server, as RFC 9068 lays it out.

        audience is the server's address: the resource indicator (RFC 8707) a client names when it
        asks for a token, which the issuer copies into aud."""
        now = int(time.time()) if issued_at is None else issued_at
        claims = {
            "iss": self.name,
            "aud": audience,
            "sub": subject,
            "client_id": client_id,
            "scope": " ".join(scopes),
            "iat": now,
            "exp": now + lifetime,
            "jti": uuid.uuid4().hex,
        }
        return jwt.encode(claims, self._key, algorithm=ALGORITHM, headers={"typ": "at+jwt"})


def public_key_at(folder: Path) -> ec.EllipticCurvePublicKey:
    """The lab's issuer's public key, as a server reads it: only the public half. A real server
    fetches it from the authorization server's published keys instead."""
    if not (folder / PUBLIC_KEY).exists():
        LabIssuer.at(folder)  # the lab's issuer doesn't exist yet: make it, as its first use would
    key = serialization.load_pem_public_key((folder / PUBLIC_KEY).read_bytes())
    assert isinstance(key, ec.EllipticCurvePublicKey)
    return key
