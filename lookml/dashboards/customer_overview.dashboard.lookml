- dashboard: customer_overview
  title: Customer overview
  layout: newspaper
  elements:
  - name: customers_by_country
    model: steward
    explore: customers
    type: looker_column
    fields: [customers.country, customers.count]
  - name: active_by_segment
    model: steward
    explore: customers
    type: looker_bar
    fields: [customers.segment, customers.active_customers]
  - name: tickets_by_category
    model: steward
    explore: customers
    type: looker_pie
    fields: [support_tickets.category, support_tickets.count]
  - name: callers_with_most_tickets
    model: steward
    explore: customers
    type: looker_grid
    fields: [customers.msisdn, support_tickets.count]
