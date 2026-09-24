# API tokens
tags: api, token, integration

## Creating a token

Open Settings, then API, and choose New token. Give it a name, copy it, and store it somewhere safe: we show a token only once. A token acts with your permissions.

## Rate limits

Each token can make 100 requests a minute. Past that, requests fail with status 429 until the minute is up. Spread requests out, or wait and try again.

## Revoking a token

Revoke a token you no longer use, or one that may have leaked, from the same page. It stops working at once, and anything that used it stops working too.
