"""Single source of truth for every question.

Each record: id, set (pretest | practice | heldout), skill (S1..S6), prompt,
reference SQL, ordered flag. `scripts/build_questions.py` runs each reference
query and freezes the expected result set into `questions.json`. The tutor, the
exercise screen and the grader all read that same record.

Skills:
  S1 INNER JOIN on keys
  S2 LEFT JOIN, keeping unmatched rows
  S3 anti-join ("never ...")
  S4 aggregate across a join (fan-out / double-counting trap)
  S5 date-range filter combined with a join
  S6 three-or-more-table join
"""

SKILLS = {
    "S1": "INNER JOIN on keys",
    "S2": "LEFT JOIN keeping unmatched rows",
    "S3": "Anti-join (rows with no match)",
    "S4": "Aggregating across a join (fan-out trap)",
    "S5": "Date-range filter with a join",
    "S6": "Joining three or more tables",
}

# transfer (held-out only): "near" = same structure as a pretest/practice item, new surface;
# "far" = combines structures (e.g. anti-join through a join, LEFT JOIN with a condition in ON).
# Primary gain is skill-matched: H1-H6 (one per skill) vs P1-P6. H7, H8 are reported separately.
QUESTIONS = [
    # ---------------- PRETEST (one per skill) ----------------
    dict(id="P1", set="pretest", skill="S1", ordered=False,
         prompt="For every order with status 'cancelled', show the order_id and the name of the customer who placed it.\nColumns: order_id, name",
         sql="""SELECT o.order_id, c.name
FROM shop.orders o JOIN shop.customers c ON c.customer_id = o.customer_id
WHERE o.status = 'cancelled'"""),
    dict(id="P2", set="pretest", skill="S2", ordered=False,
         prompt="List every category with the number of products in it. Categories with no products must appear with 0.\nColumns: category_name, product_count",
         sql="""SELECT cat.name, COUNT(p.product_id)
FROM shop.categories cat LEFT JOIN shop.products p ON p.category_id = cat.category_id
GROUP BY cat.category_id, cat.name"""),
    dict(id="P3", set="pretest", skill="S3", ordered=False,
         prompt="Find the customers who have never placed an order.\nColumns: customer_id, name",
         sql="""SELECT c.customer_id, c.name
FROM shop.customers c
WHERE NOT EXISTS (SELECT 1 FROM shop.orders o WHERE o.customer_id = c.customer_id)"""),
    dict(id="P4", set="pretest", skill="S4", ordered=False,
         prompt="For each city, show how many different orders were paid for and the total amount paid (sum of payments). Only count orders that have at least one payment.\nColumns: city, order_count, total_paid",
         sql="""SELECT c.city, COUNT(DISTINCT o.order_id), SUM(pay.amount)
FROM shop.customers c
JOIN shop.orders o ON o.customer_id = c.customer_id
JOIN shop.payments pay ON pay.order_id = o.order_id
GROUP BY c.city"""),
    dict(id="P5", set="pretest", skill="S5", ordered=False,
         prompt="Show the names of customers who placed at least one order (any status) between 1 January 2026 and 31 March 2026, both dates included. Each name once.\nColumns: name",
         sql="""SELECT DISTINCT c.name
FROM shop.customers c JOIN shop.orders o ON o.customer_id = c.customer_id
WHERE o.order_date BETWEEN DATE '2026-01-01' AND DATE '2026-03-31'"""),
    dict(id="P6", set="pretest", skill="S6", ordered=False,
         prompt="For each category, show the total quantity sold in delivered orders. Only include categories that sold something.\nColumns: category_name, total_quantity",
         sql="""SELECT cat.name, SUM(oi.quantity)
FROM shop.categories cat
JOIN shop.products p ON p.category_id = cat.category_id
JOIN shop.order_items oi ON oi.product_id = p.product_id
JOIN shop.orders o ON o.order_id = oi.order_id
WHERE o.status = 'delivered'
GROUP BY cat.category_id, cat.name"""),

    # ---------------- PRACTICE (8) ----------------
    dict(id="T1", set="practice", skill="S1", ordered=False,
         prompt="Show the name and list price of every product that was bought at least once below its list price (order_items.unit_price < products.price). Each product once.\nColumns: name, price",
         sql="""SELECT DISTINCT p.name, p.price
FROM shop.products p JOIN shop.order_items oi ON oi.product_id = p.product_id
WHERE oi.unit_price < p.price"""),
    dict(id="T2", set="practice", skill="S2", ordered=True,
         prompt="List every customer with the number of orders they have placed. Customers with no orders must show 0. Sort by customer_id.\nColumns: customer_id, name, order_count",
         sql="""SELECT c.customer_id, c.name, COUNT(o.order_id)
FROM shop.customers c LEFT JOIN shop.orders o ON o.customer_id = c.customer_id
GROUP BY c.customer_id, c.name
ORDER BY c.customer_id"""),
    dict(id="T3", set="practice", skill="S3", ordered=False,
         prompt="Find the products that have never been ordered.\nColumns: product_id, name",
         sql="""SELECT p.product_id, p.name
FROM shop.products p
WHERE NOT EXISTS (SELECT 1 FROM shop.order_items oi WHERE oi.product_id = p.product_id)"""),
    dict(id="T4", set="practice", skill="S4", ordered=False,
         prompt="For each order that was paid in more than one payment, show the order_id, the number of payments, and the order's item total (sum of quantity × unit_price).\nColumns: order_id, payment_count, items_total",
         sql="""WITH pc AS (SELECT order_id, COUNT(*) AS n FROM shop.payments GROUP BY order_id HAVING COUNT(*) > 1),
it AS (SELECT order_id, SUM(quantity * unit_price) AS total FROM shop.order_items GROUP BY order_id)
SELECT pc.order_id, pc.n, it.total FROM pc JOIN it ON it.order_id = pc.order_id"""),
    dict(id="T5", set="practice", skill="S5", ordered=True,
         prompt="For delivered orders placed in 2025, show the item revenue (sum of quantity × unit_price) for each month. Sort by month.\nColumns: month (1-12), revenue",
         sql="""SELECT EXTRACT(MONTH FROM o.order_date) AS month, SUM(oi.quantity * oi.unit_price)
FROM shop.orders o JOIN shop.order_items oi ON oi.order_id = o.order_id
WHERE o.status = 'delivered' AND o.order_date >= DATE '2025-01-01' AND o.order_date < DATE '2026-01-01'
GROUP BY 1 ORDER BY 1"""),
    dict(id="T6", set="practice", skill="S6", ordered=False,
         prompt="For every item ordered by customers from Kochi (orders of any status), show the customer's name, the order_id and the product's name.\nColumns: name, order_id, product_name",
         sql="""SELECT c.name, o.order_id, p.name
FROM shop.customers c
JOIN shop.orders o ON o.customer_id = c.customer_id
JOIN shop.order_items oi ON oi.order_id = o.order_id
JOIN shop.products p ON p.product_id = oi.product_id
WHERE c.city = 'Kochi'"""),
    dict(id="T7", set="practice", skill="S2", ordered=True,
         prompt="List every customer with the total number of units they have ordered (sum of quantity over all their orders, whatever the status, cancelled included). Customers who never ordered must show 0. Sort by total_units (highest first), then by customer_id.\nColumns: customer_id, name, total_units",
         sql="""SELECT c.customer_id, c.name, COALESCE(SUM(oi.quantity), 0) AS tu
FROM shop.customers c
LEFT JOIN shop.orders o ON o.customer_id = c.customer_id
LEFT JOIN shop.order_items oi ON oi.order_id = o.order_id
GROUP BY c.customer_id, c.name
ORDER BY tu DESC, c.customer_id"""),
    dict(id="T8", set="practice", skill="S3", ordered=False,
         prompt="Find the customers who have never ordered any product from the 'Electronics' category (orders of any status count). Customers with no orders at all are included.\nColumns: customer_id, name",
         sql="""SELECT c.customer_id, c.name
FROM shop.customers c
WHERE NOT EXISTS (
  SELECT 1 FROM shop.orders o
  JOIN shop.order_items oi ON oi.order_id = o.order_id
  JOIN shop.products p ON p.product_id = oi.product_id
  JOIN shop.categories cat ON cat.category_id = p.category_id
  WHERE o.customer_id = c.customer_id AND cat.name = 'Electronics')"""),

    # ---------------- HELD-OUT (8) — never shown before the removal test ----------------
    dict(id="H1", set="heldout", transfer="near", skill="S1", ordered=False,
         prompt="For every order with status 'shipped', show the order_id, the order_date and the city of the customer.\nColumns: order_id, order_date, city",
         sql="""SELECT o.order_id, o.order_date, c.city
FROM shop.orders o JOIN shop.customers c ON c.customer_id = o.customer_id
WHERE o.status = 'shipped'"""),
    dict(id="H2", set="heldout", transfer="far", skill="S2", ordered=False,
         prompt="List every category with the total number of units ordered (sum of quantity over every order, whatever the status, cancelled included). Categories with nothing ordered must show 0.\nColumns: category_name, units_ordered",
         sql="""SELECT cat.name, COALESCE(SUM(oi.quantity), 0)
FROM shop.categories cat
LEFT JOIN shop.products p ON p.category_id = cat.category_id
LEFT JOIN shop.order_items oi ON oi.product_id = p.product_id
GROUP BY cat.category_id, cat.name"""),
    dict(id="H3", set="heldout", transfer="far", skill="S3", ordered=False,
         prompt="Find customers who have never made a payment.\nColumns: customer_id, name",
         sql="""SELECT c.customer_id, c.name
FROM shop.customers c
WHERE NOT EXISTS (SELECT 1 FROM shop.orders o JOIN shop.payments pay ON pay.order_id = o.order_id
                  WHERE o.customer_id = c.customer_id)"""),
    dict(id="H4", set="heldout", transfer="near", skill="S4", ordered=False,
         prompt="For each customer who has made at least one payment, show their name, how many different orders they paid for, and the total amount they paid.\nColumns: name, order_count, total_paid",
         sql="""SELECT c.name, COUNT(DISTINCT o.order_id), SUM(pay.amount)
FROM shop.customers c
JOIN shop.orders o ON o.customer_id = c.customer_id
JOIN shop.payments pay ON pay.order_id = o.order_id
GROUP BY c.customer_id, c.name"""),
    dict(id="H5", set="heldout", transfer="near", skill="S5", ordered=False,
         prompt="For each product that appears in orders placed in December 2025 (any status, 1 to 31 December inclusive), show its name and the number of different December 2025 orders it appears in.\nColumns: name, order_count",
         sql="""SELECT p.name, COUNT(DISTINCT o.order_id)
FROM shop.products p
JOIN shop.order_items oi ON oi.product_id = p.product_id
JOIN shop.orders o ON o.order_id = oi.order_id
WHERE o.order_date >= DATE '2025-12-01' AND o.order_date < DATE '2026-01-01'
GROUP BY p.product_id, p.name"""),
    dict(id="H6", set="heldout", transfer="near", skill="S6", ordered=False,
         prompt="For each customer city, show the item revenue (sum of quantity × unit_price) from delivered orders.\nColumns: city, revenue",
         sql="""SELECT c.city, SUM(oi.quantity * oi.unit_price)
FROM shop.customers c
JOIN shop.orders o ON o.customer_id = c.customer_id
JOIN shop.order_items oi ON oi.order_id = o.order_id
WHERE o.status = 'delivered'
GROUP BY c.city"""),
    dict(id="H7", set="heldout", transfer="far", skill="S2", ordered=False,
         prompt="List every customer with the date of their FIRST delivered order. Customers with no delivered order must still appear, with NULL as the date.\nColumns: customer_id, name, first_delivered_date",
         sql="""SELECT c.customer_id, c.name, MIN(o.order_date)
FROM shop.customers c
LEFT JOIN shop.orders o ON o.customer_id = c.customer_id AND o.status = 'delivered'
GROUP BY c.customer_id, c.name"""),
    dict(id="H8", set="heldout", transfer="far", skill="S3", ordered=False,
         prompt="Find the products that no customer from Chennai has ever ordered (orders of any status count).\nColumns: name",
         sql="""SELECT p.name
FROM shop.products p
WHERE NOT EXISTS (
  SELECT 1 FROM shop.order_items oi
  JOIN shop.orders o ON o.order_id = oi.order_id
  JOIN shop.customers c ON c.customer_id = o.customer_id
  WHERE oi.product_id = p.product_id AND c.city = 'Chennai')"""),
]
