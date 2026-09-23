using Helpdesk.Data;

namespace Helpdesk.Services;

/// <summary>The business rules. They call data and know nothing of api.</summary>
public static class Tickets
{
    /// <summary>A ticket's title, or a placeholder when it has none.</summary>
    public static string Title(int id)
    {
        var title = TicketStore.Title(id);
        return title.Length == 0 ? "(untitled)" : title;
    }
}
