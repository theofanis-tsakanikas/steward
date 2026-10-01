- dashboard: churn_risk
  title: Churn risk (built against a field nobody modelled)
  layout: newspaper
  elements:
  - name: at_risk
    model: steward
    explore: customers
    type: looker_grid
    fields: [customers.segment, customers.churn_score]
