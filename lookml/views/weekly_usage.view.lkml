view: weekly_usage {
  sql_table_name: `analytics.weekly_usage_by_cell` ;;

  dimension: week_start {
    type: date
    sql: ${TABLE}.week_start ;;
  }
  dimension: country {
    sql: ${TABLE}.country ;;
  }
  dimension: cell_id {
    sql: ${TABLE}.cell_id ;;
  }
  measure: total_events {
    type: sum
    sql: ${TABLE}.events ;;
  }
  measure: total_volume_mb {
    type: sum
    sql: ${TABLE}.total_mb ;;
  }
  measure: subscriber_weeks {
    description: "Sum of weekly distinct subscribers — a person active in three weeks counts three times. Not a count of people."
    type: sum
    sql: ${TABLE}.subscribers ;;
  }
}
