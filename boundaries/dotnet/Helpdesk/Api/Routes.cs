using Helpdesk.Services;

namespace Helpdesk.Api;

/// <summary>The top layer. It calls services, never data directly.</summary>
public static class Routes
{
    /// <summary>What a route would show as a ticket's title.</summary>
    public static string TicketTitle(int id) => Tickets.Title(id);
}
