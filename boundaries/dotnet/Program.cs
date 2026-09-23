// The helpdesk's layer rule with NetArchTest, which reads the compiled assembly (chapter 16).
// NetArchTest works with any test framework; this runs it as a small program so that CI needs
// nothing else. It exits 1 if the helpdesk breaks the rule or the planted violation isn't caught.
using System.Reflection;
using NetArchTest.Rules;

// Each layer and the layers it must never depend on: a lower layer never uses a higher one, and
// Api never skips Services to reach Data.
var rules = new Dictionary<string, string[]>
{
    ["Data"] = new[] { "Services", "Api" },
    ["Services"] = new[] { "Api" },
    ["Api"] = new[] { "Data" },
};

List<string> Check(string root)
{
    var problems = new List<string>();
    foreach (var (layer, forbidden) in rules)
    {
        var types = Types.InAssembly(Assembly.GetExecutingAssembly()).That().ResideInNamespace($"{root}.{layer}");
        // NetArchTest reports success for a rule that selected no types, so make sure there are some.
        if (!types.GetTypes().Any())
        {
            problems.Add($"{root}.{layer} has no types, so its rule would check nothing.");
            continue;
        }
        var names = forbidden.Select(name => $"{root}.{name}").ToArray();
        var result = types.ShouldNot().HaveDependencyOnAny(names).GetResult();
        if (!result.IsSuccessful)
        {
            problems.Add(
                $"{string.Join(", ", result.FailingTypeNames)} must not depend on {string.Join(" or ", names)}. " +
                "Routes call services and services call data: move the code into the layer that is allowed to use it.");
        }
    }
    return problems;
}

var helpdesk = Check("Helpdesk");
foreach (var problem in helpdesk)
{
    Console.Error.WriteLine(problem);
}

var planted = Check("Planted");
var caught = planted.Count == 1 && planted[0].StartsWith("Planted.Data.PlantedStore ");
if (!caught)
{
    Console.Error.WriteLine($"The planted violation in Planted.Data was not caught as expected: {string.Join(" | ", planted)}");
}

var ok = helpdesk.Count == 0 && caught;
Console.WriteLine(ok ? "The helpdesk keeps its layers, and the planted violation is caught." : "The layer rule failed.");
return ok ? 0 : 1;
