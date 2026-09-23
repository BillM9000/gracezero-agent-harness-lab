// Package data is the bottom layer. It imports nothing else from the helpdesk.
package data

var titles = map[int]string{1: "Password reset email never arrives"}

// Title returns a stored ticket title, or "" when there is none.
func Title(id int) string {
	return titles[id]
}
