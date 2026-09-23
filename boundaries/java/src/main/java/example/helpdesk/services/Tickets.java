package example.helpdesk.services;

import example.helpdesk.data.TicketStore;

/** The business rules. They call data and know nothing of api. */
public final class Tickets {
    private Tickets() {}

    /** A ticket's title, or a placeholder when it has none. */
    public static String title(int id) {
        String title = TicketStore.title(id);
        return title.isEmpty() ? "(untitled)" : title;
    }
}
