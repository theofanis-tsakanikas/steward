- dashboard: legacy_churn
  title: Churn signals (legacy)
  layout: newspaper
  elements:
  - name: tickets_by_segment
    model: steward
    explore: customers
    type: looker_bar
    fields: [customers.segment, customers.birth_year, support_tickets.count]
