// The helpdesk's layer rule in Go (chapter 16), using only the standard library: go/build reads each
// package's imports without compiling it. Run with: go test ./...
package layers_test

import (
	"go/build"
	"io/fs"
	"path/filepath"
	"slices"
	"strings"
	"testing"
)

const module = "example.com/helpdesk"

// allowed lists, for each package, the only helpdesk packages it may import: api calls services,
// services call data, and data calls nothing. Anything else, including a helpdesk package added
// later, is a violation. TestEveryPackageHasARule fails when a package in the tree has no entry here.
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

// packages returns every folder under root, at any depth, that holds a Go file other than a test,
// as a slash-separated path from root. testdata and folders starting with "." or "_" are skipped,
// as the go tool skips them.
func packages(t *testing.T, root string) []string {
	t.Helper()
	var found []string
	err := filepath.WalkDir(root, func(path string, entry fs.DirEntry, err error) error {
		if err != nil {
			return err
		}
		name := entry.Name()
		if entry.IsDir() {
			if path != root && (name == "testdata" || strings.HasPrefix(name, ".") || strings.HasPrefix(name, "_")) {
				return filepath.SkipDir
			}
			return nil
		}
		if strings.HasSuffix(name, ".go") && !strings.HasSuffix(name, "_test.go") {
			dir, _ := filepath.Rel(root, filepath.Dir(path))
			if dir != "." && !slices.Contains(found, filepath.ToSlash(dir)) {
				found = append(found, filepath.ToSlash(dir))
			}
		}
		return nil
	})
	if err != nil {
		t.Fatalf("walking %s: %v", root, err)
	}
	slices.Sort(found)
	return found
}

func TestEveryPackageHasARule(t *testing.T) {
	// The rule is checked for the packages in allowed; one added later, or nested in another, would
	// otherwise go unchecked.
	for _, dir := range packages(t, ".") {
		if _, ok := allowed[dir]; !ok {
			t.Errorf("%s is a package with no entry in allowed, so its imports go unchecked. Add it, with the helpdesk packages it may import.", dir)
		}
	}
}

func TestANewPackageIsFound(t *testing.T) {
	// The control: a package planted in testdata, nested, is found when the walk starts there.
	if found := packages(t, "testdata/planted"); !slices.Equal(found, []string{"data"}) {
		t.Fatalf("the planted package testdata/planted/data was not found; found %v", found)
	}
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
