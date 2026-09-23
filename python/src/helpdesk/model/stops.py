"""Turn a model response into final text, or stop and say why it isn't final.

A refusal or a cut-off answer arrives as a normal, successful response. Code that only checks for
errors will treat either one as a finished answer. Every call site that wants text calls
final_text instead of reading response.text directly.
"""

from __future__ import annotations

from helpdesk.model.types import ModelResponse


class IncompleteResponse(Exception):
    """The response is not a finished answer. The message says what to do instead."""


class Refused(IncompleteResponse):
    pass


class Truncated(IncompleteResponse):
    pass


class NotFinished(IncompleteResponse):
    pass


def final_text(response: ModelResponse) -> str:
    match response.stop_reason:
        case "end_turn" | "stop_sequence":
            return response.text
        case "refusal":
            raise Refused(
                "The model declined this request (stop_reason refusal). A refusal is a successful "
                "response, so record it as its own event; retry on a different model only if your "
                "policy allows it, and never show an empty answer as if it were one."
            )
        case "max_tokens":
            raise Truncated(
                "The answer was cut off at max_tokens. Raise max_tokens, ask for less, or continue "
                "in another call. Do not use the partial text as if it were complete."
            )
        case "model_context_window_exceeded":
            raise Truncated(
                "The answer filled the model's context window and was cut off. Send less: trim "
                "the history, drop what the task doesn't need, or split the task."
            )
        case "tool_use" | "pause_turn":
            raise NotFinished(
                f"The model is not done (stop_reason {response.stop_reason}): it is waiting for a "
                "tool result or to be resumed. Keep the loop going; chapter 3 shows how."
            )
        case _:
            # Vendors add stop reasons. An unknown one is treated as unfinished, never as an answer.
            raise IncompleteResponse(
                f"Unknown stop_reason {response.stop_reason!r}. Look it up in the vendor's "
                "documentation and add a case here before trusting the text."
            )
