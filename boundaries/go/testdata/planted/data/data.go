// Package data breaks the layer rule on purpose: the bottom layer importing services. The go tool
// ignores testdata folders, so this is never built; layers_test.go only reads its imports.
package data

import "example.com/helpdesk/services"

// Title asks the layer above for the answer, which is what the rule forbids.
func Title(id int) string {
	return services.Title(id)
}
