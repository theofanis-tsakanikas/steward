- dashboard: billing_health
  title: Billing health
  layout: newspaper
  elements:
  - name: amount_by_status
    model: steward
    explore: customers
    type: looker_column
    fields: [billing.status, billing.total_amount]
  - name: paying_customers
    model: steward
    explore: customers
    type: single_value
    fields: [billing.active_customers]
