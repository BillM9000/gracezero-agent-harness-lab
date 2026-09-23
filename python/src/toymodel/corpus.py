"""Invented support replies, the only text the toy models ever see.

The replies disagree on purpose. Three old replies say reset emails can take up to an hour; one
newer reply says ten minutes, which matches the helpdesk's current knowledge-base article.
"""

SUPPORT_REPLIES = [
    "reset emails can take up to an hour so please wait before trying again",
    "reset emails can take up to an hour and sometimes land in spam",
    "reset emails can take up to an hour during busy periods",
    "reset emails can take up to ten minutes so check your spam folder",
    "use the forgot password link on the login page to reset your password",
    "your password must be at least twelve characters long",
    "plan changes take effect at the next billing date",
    "refunds are not automatic so please contact billing",
    "settings then export produces a csv of every project you own",
    "the export includes every project you own and every ticket you opened",
]
