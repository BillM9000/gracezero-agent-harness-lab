package example.planted.data;

import example.planted.services.PlantedTickets;

/** The planted violation: the bottom layer calling a service. */
public final class PlantedStore {
    private PlantedStore() {}

    public static String title(int id) {
        return PlantedTickets.title(id);
    }
}
