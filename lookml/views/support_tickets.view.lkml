view: support_tickets {
  sql_table_name: `crm.support_tickets` ;;

  dimension: ticket_id {
    primary_key: yes
    sql: ${TABLE}.ticket_id ;;
  }
  dimension: customer_id {
    sql: ${TABLE}.customer_id ;;
  }
  dimension: category {
    sql: ${TABLE}.category ;;
  }
  dimension: channel {
    sql: ${TABLE}.channel ;;
  }
  dimension_group: opened {
    type: time
    timeframes: [date, week, month]
    sql: ${TABLE}.opened_at ;;
  }
  measure: count {
    type: count
  }
}
