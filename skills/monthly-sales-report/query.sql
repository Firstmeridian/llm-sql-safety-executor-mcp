SELECT
    DATE(order_date) AS date,
    COUNT(*) AS order_count,
    SUM(amount) AS revenue,
    ROUND(AVG(amount), 2) AS avg_order_value
FROM orders
WHERE YEAR(order_date) = :year
  AND MONTH(order_date) = :month
GROUP BY DATE(order_date)
ORDER BY date ASC
