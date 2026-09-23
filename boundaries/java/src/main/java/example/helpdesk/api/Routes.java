package example.helpdesk.api;

import example.helpdesk.services.Tickets;

/** The top layer. It calls services, never data directly. */
public final class Routes {
    private Routes() {}

    /** What a route would show as a ticket's title. */
    public static String ticketTitle(int id) {
        return Tickets.title(id);
    }
}
