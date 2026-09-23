// A copy of the layers with one violation planted in its data layer. Program.cs checks it with the
// same rule and requires the rule to fail; if it passed, the helpdesk passing would prove nothing.

namespace Planted.Api
{
    public static class PlantedRoutes
    {
        public static string TicketTitle(int id) => Planted.Services.PlantedTickets.Title(id);
    }
}

namespace Planted.Services
{
    public static class PlantedTickets
    {
        public static string Title(int id) => "(untitled)";
    }
}

namespace Planted.Data
{
    /// <summary>The planted violation: the bottom layer calling a service.</summary>
    public static class PlantedStore
    {
        public static string Title(int id) => Planted.Services.PlantedTickets.Title(id);
    }
}
