connection: "bq_halverra"

include: "/views/*.view.lkml"
include: "/dashboards/*.dashboard.lookml"

explore: customers {
  description: "Customers with their tickets and invoices."
  join: support_tickets {
    sql_on: ${customers.customer_id} = ${support_tickets.customer_id} ;;
    relationship: one_to_many
  }
  join: billing {
    sql_on: ${customers.customer_id} = ${billing.customer_id} ;;
    relationship: one_to_many
  }
}

explore: weekly_usage {
  description: "Weekly network usage per cell, aggregated (k >= 5 subscribers)."
}
