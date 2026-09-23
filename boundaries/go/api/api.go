// Package api is the top layer. It calls services, never data directly.
package api

import "example.com/helpdesk/services"

// TicketTitle is what a route would show as a ticket's title.
func TicketTitle(id int) string {
	return services.Title(id)
}
