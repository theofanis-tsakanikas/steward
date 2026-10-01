- dashboard: network_usage
  title: Network usage by cell
  layout: newspaper
  elements:
  - name: volume_by_week
    model: steward
    explore: weekly_usage
    type: looker_line
    fields: [weekly_usage.week_start, weekly_usage.total_volume_mb]
  - name: busiest_cells
    model: steward
    explore: weekly_usage
    type: looker_grid
    fields: [weekly_usage.country, weekly_usage.cell_id, weekly_usage.total_events, weekly_usage.subscriber_weeks]
