// The helpdesk's layer rule in Go (chapter 16), using only the standard library: go/build reads each
// package's imports without compiling it. Run with: go test ./...
package layers_test

import (
	"go/build"
	"slices"
	"strings"
	"testing"
)

const module = "example.com/helpdesk"

// allowed lists, for each package, the only helpdesk packages it may import: api calls services,
// services call data, and data calls nothing. Anything else, including a helpdesk package added
// later, is a violation.
var allowed = map[string][]string{
	"api":      {module + "/services"},
	"services": {module + "/data"},
	"data":     {},
}

// violations returns the helpdesk packages that the package in dir imports without being allowed to.
func violations(t *testing.T, dir string, allow []string) []string {
	t.Helper()
	pkg, err := build.ImportDir(dir, 0)
	if err != nil {
		// A folder with no Go files is an error, so a moved package fails here instead of passing
		// with nothing checked.
		t.Fatalf("reading %s: %v", dir, err)
	}
	var found []string
	for _, path := range pkg.Imports {
		if strings.HasPrefix(path, module+"/") && !slices.Contains(allow, path) {
			found = append(found, path)
		}
	}
	return found
}

func TestLayers(t *testing.T) {
	for dir, allow := range allowed {
		if found := violations(t, dir, allow); len(found) > 0 {
			t.Errorf("%s imports %v, but may import only %v. Routes call services and services call data: move the code into the layer that is allowed to use it.", dir, found, allow)
		}
	}
}

func TestAPlantedViolationIsCaught(t *testing.T) {
	// The control: if this passed, TestLayers passing would prove nothing.
	found := violations(t, "testdata/planted/data", allowed["data"])
	if !slices.Equal(found, []string{module + "/services"}) {
		t.Fatalf("the planted import of %s/services was not caught; found %v", module, found)
	}
}
