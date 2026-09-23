"""The triage assistant: a product agent that works inside the helpdesk.

It sits beside the API routes, above the services. It may use helpdesk.services and
helpdesk.model; it must never import helpdesk.data or helpdesk.api.
"""
