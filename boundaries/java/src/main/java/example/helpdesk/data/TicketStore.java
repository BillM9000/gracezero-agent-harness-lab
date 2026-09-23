package example.helpdesk.data;

import java.util.Map;

/** The bottom layer. It imports nothing else from the helpdesk. */
public final class TicketStore {
    private static final Map<Integer, String> TITLES = Map.of(1, "Password reset email never arrives");

    private TicketStore() {}

    /** A stored ticket title, or "" when there is none. */
    public static String title(int id) {
        return TITLES.getOrDefault(id, "");
    }
}
