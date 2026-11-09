-- Learning OS — practice schema ("Kovai Mart", a fictional online store)
-- Learners query ONLY schema `shop`. App data lives in schema `app` (see 03_app.sql).

DROP SCHEMA IF EXISTS shop CASCADE;
CREATE SCHEMA shop;

CREATE TABLE shop.customers (
    customer_id   INT PRIMARY KEY,
    name          TEXT NOT NULL,
    city          TEXT NOT NULL,
    signup_date   DATE NOT NULL
);

CREATE TABLE shop.categories (
    category_id   INT PRIMARY KEY,
    name          TEXT NOT NULL
);

CREATE TABLE shop.products (
    product_id    INT PRIMARY KEY,
    name          TEXT NOT NULL,
    category_id   INT NOT NULL REFERENCES shop.categories(category_id),
    price         NUMERIC(10,2) NOT NULL
);

CREATE TABLE shop.orders (
    order_id      INT PRIMARY KEY,
    customer_id   INT NOT NULL REFERENCES shop.customers(customer_id),
    order_date    DATE NOT NULL,
    status        TEXT NOT NULL CHECK (status IN ('delivered','shipped','cancelled'))
);

CREATE TABLE shop.order_items (
    order_id      INT NOT NULL REFERENCES shop.orders(order_id),
    product_id    INT NOT NULL REFERENCES shop.products(product_id),
    quantity      INT NOT NULL CHECK (quantity > 0),
    unit_price    NUMERIC(10,2) NOT NULL,
    PRIMARY KEY (order_id, product_id)
);

-- Payments for a non-cancelled order add up to its item total + a 40.00 delivery fee.
-- Cancelled orders have no payments. One order can be paid in several instalments -> joining payments and
-- order_items through orders multiplies rows (the fan-out trap, skill S4).
CREATE TABLE shop.payments (
    payment_id    INT PRIMARY KEY,
    order_id      INT NOT NULL REFERENCES shop.orders(order_id),
    amount        NUMERIC(10,2) NOT NULL,
    method        TEXT NOT NULL CHECK (method IN ('upi','card','cod')),
    paid_on       DATE NOT NULL
);
