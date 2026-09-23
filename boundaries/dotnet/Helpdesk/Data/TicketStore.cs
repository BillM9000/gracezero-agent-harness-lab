namespace Helpdesk.Data;

/// <summary>The bottom layer. It uses nothing else from the helpdesk.</summary>
public static class TicketStore
{
    private static readonly Dictionary<int, string> Titles = new() { [1] = "Password reset email never arrives" };

    /// <summary>A stored ticket title, or "" when there is none.</summary>
    public static string Title(int id) => Titles.GetValueOrDefault(id, "");
}
