view: billing {
  sql_table_name: `finance.billing` ;;

  dimension: invoice_id {
    primary_key: yes
    sql: ${TABLE}.invoice_id ;;
  }
  dimension: customer_id {
    sql: ${TABLE}.customer_id ;;
  }
  dimension: status {
    sql: ${TABLE}.status ;;
  }
  dimension: amount {
    type: number
    sql: ${TABLE}.amount ;;
  }
  dimension_group: issue {
    type: time
    timeframes: [date, month]
    sql: ${TABLE}.issue_date ;;
  }
  measure: total_amount {
    type: sum
    sql: ${amount} ;;
  }
  measure: active_customers {
    description: "Customers who paid an invoice — finance's reading of 'active'."
    type: count_distinct
    sql: ${customer_id} ;;
    filters: [status: "paid"]
    tags: ["glossary:active_customer"]
  }
}
