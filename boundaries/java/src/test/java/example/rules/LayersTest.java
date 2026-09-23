package example.rules;

import static com.tngtech.archunit.library.Architectures.layeredArchitecture;
import static org.junit.jupiter.api.Assertions.assertTrue;

import com.tngtech.archunit.core.importer.ClassFileImporter;
import com.tngtech.archunit.lang.ArchRule;
import com.tngtech.archunit.lang.EvaluationResult;
import org.junit.jupiter.api.Test;

/** The helpdesk's layer rule with ArchUnit, which reads compiled classes (chapter 16). */
class LayersTest {

    /** A lower layer never uses a higher one, and api never skips services to reach data. */
    static ArchRule layersOf(String root) {
        return layeredArchitecture()
                .consideringAllDependencies()
                .layer("Api").definedBy(root + ".api..")
                .layer("Services").definedBy(root + ".services..")
                .layer("Data").definedBy(root + ".data..")
                .whereLayer("Api").mayNotBeAccessedByAnyLayer()
                .whereLayer("Services").mayOnlyBeAccessedByLayers("Api")
                .whereLayer("Data").mayOnlyBeAccessedByLayers("Services")
                .because("routes call services and services call data: move the code into the layer that is allowed to use it");
    }

    @Test
    void theHelpdeskKeepsItsLayers() {
        layersOf("example.helpdesk").check(new ClassFileImporter().importPackages("example.helpdesk"));
    }

    @Test
    void aPlantedViolationIsCaught() {
        // The control: if this rule passed, the test above passing would prove nothing.
        EvaluationResult result =
                layersOf("example.planted").evaluate(new ClassFileImporter().importPackages("example.planted"));
        assertTrue(result.hasViolation(), "the planted call from data to services was not caught");
        assertTrue(
                result.getFailureReport().getDetails().stream()
                        .anyMatch(detail -> detail.contains("PlantedStore") && detail.contains("PlantedTickets")),
                () -> "the failure did not name the planted call: " + result.getFailureReport().getDetails());
    }
}
