// Package services holds the business rules. It calls data and knows nothing of api.
package services

import "example.com/helpdesk/data"

// Title returns a ticket's title, or a placeholder when it has none.
func Title(id int) string {
	if title := data.Title(id); title != "" {
		return title
	}
	return "(untitled)"
}
