package example.planted.api;

import example.planted.services.PlantedTickets;

/** Part of a copy of the layers with one violation planted in its data layer. */
public final class PlantedRoutes {
    private PlantedRoutes() {}

    public static String ticketTitle(int id) {
        return PlantedTickets.title(id);
    }
}
