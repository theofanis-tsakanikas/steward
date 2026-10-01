view: customers {
  sql_table_name: `crm.customers` ;;

  dimension: customer_id {
    primary_key: yes
    sql: ${TABLE}.customer_id ;;
  }
  dimension: country {
    sql: ${TABLE}.country ;;
  }
  dimension: segment {
    sql: ${TABLE}.segment ;;
  }
  dimension: msisdn {
    description: "Hashed for the BI connection (SHA-256). Pseudonymised, not anonymised: an unsalted hash of a phone number can be reversed by enumeration — a join key, not a display value."
    sql: ${TABLE}.msisdn ;;
  }
  dimension: birth_year {
    type: number
    sql: EXTRACT(YEAR FROM ${TABLE}.birth_date) ;;
  }
  dimension: has_active_contract {
    type: yesno
    sql: EXISTS(SELECT 1 FROM UNNEST(${TABLE}.contracts) AS c WHERE c.status = 'active') ;;
  }
  measure: count {
    type: count
  }
  measure: active_customers {
    description: "Customers with at least one active contract."
    type: count_distinct
    sql: ${customer_id} ;;
    filters: [has_active_contract: "yes"]
    tags: ["glossary:active_customer"]
  }
}
